"""Asking a worker to bring a ledger's search index up to date, through
Temporal.

The archive host and the worker are separate programs. After the host
stores a new event, it asks the worker to index the new files by
starting a Temporal workflow. This module holds the host's side of that:
the adapter that starts the workflow.

It also holds the few names the two programs must agree on, such as the
workflow's name. The worker application imports them from here. The
host cannot import them from the worker, because nothing may import an
application.
"""

import asyncio
import sys
from dataclasses import dataclass

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter

#: The name the index workflow is registered under.
INDEX_WORKFLOW = "ArchiveIndexWorkflow"

#: The name of the schedule that indexes every registered ledger. Also
#: the start of each workflow id.
INDEX_SCHEDULE = "archive-index"


def index_workflow_id(ledger_id: str) -> str:
    """The id of the workflow run that indexes one ledger. One id for
    each ledger means two runs for the same ledger cannot overlap."""
    return f"{INDEX_SCHEDULE}/{ledger_id}"


@dataclass(frozen=True)
class TemporalAddress:
    """Where a Temporal server is, and which task queue the worker
    listens on."""

    address: str
    namespace: str
    task_queue: str


class TemporalIndexingRequests:
    """Implements ``IndexingRequestService`` by starting the index
    workflow for one ledger. It does not wait for the workflow to
    finish.

    If a run for that ledger is already going, nothing new is started.
    If Temporal cannot be reached, the failure is printed to stderr and
    nothing is raised: the schedule will index the ledger later anyway.
    """

    def __init__(self, where: TemporalAddress) -> None:
        self._where = where

    async def _start(self, ledger_id: str) -> None:
        client = await Client.connect(
            self._where.address,
            namespace=self._where.namespace,
            data_converter=pydantic_data_converter,
        )
        await client.start_workflow(
            INDEX_WORKFLOW,
            {"ledgers": [ledger_id]},
            id=index_workflow_id(ledger_id),
            task_queue=self._where.task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )

    def request_catch_up(self, ledger_id: str) -> None:
        try:
            asyncio.run(self._start(ledger_id))
        except Exception as exc:  # this interface must never raise
            print(
                f"archive index: could not ask for {ledger_id} to be "
                f"indexed: {exc}",
                file=sys.stderr,
                flush=True,
            )
