"""The worker program.

It connects to a Temporal server, listens on a task queue, and runs the
workflows and activities it is given work for. Today that is one job:
keeping the archive's search index up to date (``archive_index.py``).

Run it with ``python -m bugflow.apps.worker``.

The worker reads the archive's tables and does not make them. The archive
host runs the scripts that do, when it starts.
"""

import asyncio
import os
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import (
    SandboxedWorkflowRunner,
    SandboxRestrictions,
)

from bugflow.apps.worker.archive_index import (
    ArchiveIndexWorkflow,
    activities_from_environment,
    ensure_schedule,
)

#: How many activities may run at the same time. Activities here are
#: ordinary blocking functions, so each runs on a thread.
ACTIVITY_THREADS = 8


def workflow_runner() -> SandboxedWorkflowRunner:
    """The sandbox Temporal runs workflow code in, adjusted for pydantic.

    Temporal reloads modules inside the sandbox to catch workflow code
    that is not repeatable. ``pydantic_core`` is a compiled module that
    cannot be reloaded that way, so it is passed through unchanged.
    """
    return SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules(
            "pydantic_core"
        )
    )


async def run(environ: Mapping[str, str]) -> None:
    """Run the worker until it is stopped.

    Required settings: ``TEMPORAL_ADDRESS`` and ``TEMPORAL_TASK_QUEUE``.
    ``TEMPORAL_NAMESPACE`` defaults to ``default``. The settings for
    indexing are described in ``archive_index.activities_from_environment``.
    """
    address = environ.get("TEMPORAL_ADDRESS", "")
    task_queue = environ.get("TEMPORAL_TASK_QUEUE", "")
    if not (address and task_queue):
        raise ValueError(
            "TEMPORAL_ADDRESS and TEMPORAL_TASK_QUEUE are required; the "
            "worker does not start without a Temporal server and a task "
            "queue to listen on"
        )
    indexing = activities_from_environment(environ)
    if indexing is None:
        raise ValueError(
            "DATABASE_URL, ARCHIVE_S3_ENDPOINT, ARCHIVE_S3_BUCKET, "
            "WORKER_ARCHIVE_S3_ACCESS_KEY and WORKER_ARCHIVE_S3_SECRET_KEY "
            "are required; without them the worker has nothing to do"
        )
    client = await Client.connect(
        address,
        namespace=environ.get("TEMPORAL_NAMESPACE") or "default",
        data_converter=pydantic_data_converter,
    )
    await ensure_schedule(client, task_queue)
    with ThreadPoolExecutor(max_workers=ACTIVITY_THREADS) as executor:
        await Worker(
            client,
            task_queue=task_queue,
            workflows=[ArchiveIndexWorkflow],
            activities=indexing.all(),
            activity_executor=executor,
            workflow_runner=workflow_runner(),
        ).run()


def main() -> None:
    asyncio.run(run(os.environ))
