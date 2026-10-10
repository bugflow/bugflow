"""Tests of a worker on a server with nothing installed: no policy
deployment, no forge token and no key for a judge. It starts, serves
the archive's search index and reviews nothing.

Run against Temporal's test server. Skipped unless DATABASE_URL names a
Postgres server.
"""

import asyncio
import uuid
from dataclasses import replace

import pytest
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment

from bugflow.apps.worker.archive_index import (
    ArchiveIndexInput,
    ArchiveIndexResult,
    ArchiveIndexWorkflow,
)
from bugflow.apps.worker.parts import WorkerParts
from bugflow.apps.worker.worker import parts_from_environment, run
from bugflow.archive.infrastructure.temporal_indexing import INDEX_WORKFLOW

#: The archive's settings. The store is never reached: no ledger is
#: bound, so no file is fetched.
ARCHIVE = {
    "ARCHIVE_S3_ENDPOINT": "https://objects.invalid",
    "ARCHIVE_S3_BUCKET": "archives",
    "WORKER_ARCHIVE_S3_ACCESS_KEY": "a",
    "WORKER_ARCHIVE_S3_SECRET_KEY": "s",
}


def address_of(env: WorkflowEnvironment) -> str:
    return env.client.service_client.config.target_host


def test_only_the_archive_index_is_registered(database_url: str) -> None:
    parts = parts_from_environment({"DATABASE_URL": database_url, **ARCHIVE})

    assert parts.workflows == (ArchiveIndexWorkflow,)
    assert [one.__name__ for one in parts.activities] == [
        "bound_ledgers",
        "index_archive",
    ]
    assert parts.judging == ()
    assert parts.assessing == {}
    assert parts.before_serving == ()
    assert len(parts.schedules) == 1
    assert parts.lines == (
        "indexes the archives it is bound to",
        "reviews nothing: no policy deployment is in force",
    )


def test_it_starts_and_serves_the_archive_index(
    database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    async def scenario() -> ArchiveIndexResult:
        async with await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        ) as env:
            environ = {
                "DATABASE_URL": database_url,
                "TEMPORAL_ADDRESS": address_of(env),
                "TEMPORAL_NAMESPACE": env.client.namespace,
                "TEMPORAL_TASK_QUEUE": f"test-{uuid.uuid4()}",
                **ARCHIVE,
            }
            # The test server has no schedules, so the one that starts
            # the index every few minutes is left out and the workflow
            # is started here.
            parts = replace(parts_from_environment(environ), schedules=())
            stop = asyncio.Event()
            serving = asyncio.create_task(run(environ, parts, stop))
            try:
                result: ArchiveIndexResult = await env.client.execute_workflow(
                    INDEX_WORKFLOW,
                    ArchiveIndexInput(),
                    id=f"index-{uuid.uuid4()}",
                    task_queue=environ["TEMPORAL_TASK_QUEUE"],
                    result_type=ArchiveIndexResult,
                )
            finally:
                stop.set()
                await serving
            return result

    result = asyncio.run(scenario())

    assert result == ArchiveIndexResult(indexed=(), failed=())
    printed = capsys.readouterr().out
    assert "worker polling test-" in printed
    assert "-judge" not in printed
    assert "worker reviews nothing: no policy deployment is in force" in (
        printed
    )


def test_with_no_settings_at_all_there_is_nothing_to_do() -> None:
    environ = {"TEMPORAL_ADDRESS": "nowhere:7233", "TEMPORAL_TASK_QUEUE": "q"}
    with pytest.raises(ValueError, match="nothing to do: indexes no archive"):
        asyncio.run(run(environ))


def test_without_a_temporal_server_named_it_does_not_start() -> None:
    with pytest.raises(ValueError, match="TEMPORAL_ADDRESS"):
        asyncio.run(run({}, WorkerParts()))
