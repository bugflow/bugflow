"""Tests of the index workflow.

The workflow is run on Temporal's test server, which skips over waiting
time. The two activities are replaced by fakes that record what they
were asked to do, so what is tested is the workflow's own steps: list
the registered ledgers when none is given, index each one, and carry on
past a ledger that fails.

The last test replays a recorded history. See its docstring.
"""

import asyncio
import os
import re
import uuid
from pathlib import Path

from temporalio import activity, workflow
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

with workflow.unsafe.imports_passed_through():
    from bugflow.apps.worker.archive_index import (
        BOUND_LEDGERS_ACTIVITY,
        INDEX_ARCHIVE_ACTIVITY,
        ArchiveIndexInput,
        ArchiveIndexResult,
        ArchiveIndexWorkflow,
    )
    from bugflow.apps.worker.worker import workflow_runner
    from bugflow.archive.dtos.index_archive import (
        IndexArchiveRequest,
        IndexArchiveResponse,
    )
    from bugflow.archive.infrastructure.temporal_indexing import (
        INDEX_WORKFLOW,
        TemporalAddress,
        TemporalIndexingRequests,
        index_workflow_id,
    )

BOUND = [
    "0f1e2d3c-4b5a-4968-8778-a6b5c4d3e2f1",
    "2b3c4d5e-6f70-4a8b-9c0d-1e2f3a4b5c6d",
]
UNBOUND = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
HISTORY = Path(__file__).parent / "histories" / "archive_index.json"

asked: list[str] = []
listed = 0


@activity.defn(name=BOUND_LEDGERS_ACTIVITY)
async def fake_bound_ledgers() -> list[str]:
    global listed
    listed += 1
    return list(BOUND)


@activity.defn(name=INDEX_ARCHIVE_ACTIVITY)
async def fake_index_archive(
    request: IndexArchiveRequest,
) -> IndexArchiveResponse:
    asked.append(request.ledger_id)
    if request.ledger_id == UNBOUND:
        raise ApplicationError("No ledger is kept", non_retryable=True)
    return IndexArchiveResponse(
        ledger_id=request.ledger_id, events=3, files=len(asked)
    )


def index(
    ledgers: tuple[str, ...] = (),
    histories: list[WorkflowHistory] | None = None,
) -> ArchiveIndexResult:
    """Run the workflow once on the test server and return its result.
    If ``histories`` is given, the run's history is added to it."""

    async def run() -> ArchiveIndexResult:
        async with await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        ) as env:
            queue = f"archive-index-{uuid.uuid4()}"
            async with Worker(
                env.client,
                task_queue=queue,
                workflows=[ArchiveIndexWorkflow],
                activities=[fake_bound_ledgers, fake_index_archive],
                workflow_runner=workflow_runner(),
            ):
                handle = await env.client.start_workflow(
                    ArchiveIndexWorkflow.run,
                    ArchiveIndexInput(ledgers=ledgers),
                    id=f"archive-index-{uuid.uuid4()}",
                    task_queue=queue,
                )
                result: ArchiveIndexResult = await handle.result()
                if histories is not None:
                    histories.append(await handle.fetch_history())
                return result

    return asyncio.run(run())


def anonymous(history: str) -> str:
    """Remove the recording machine's host name and any stack traces
    from a history before it is saved. Neither matters for a replay."""
    history = re.sub(
        r'"stackTrace": "(?:[^"\\]|\\.)*"', '"stackTrace": ""', history
    )
    return re.sub(r'"identity": "[^"]*"', '"identity": "recorded"', history)


def test_given_no_ledger_every_bound_one_is_read() -> None:
    global listed
    asked.clear()
    listed = 0

    result = index()

    assert listed == 1
    assert asked == BOUND
    assert [one.ledger_id for one in result.indexed] == BOUND
    assert result.failed == ()


def test_given_a_ledger_that_one_alone_is_read() -> None:
    global listed
    asked.clear()
    listed = 0

    result = index((BOUND[1],))

    assert listed == 0
    assert asked == [BOUND[1]]
    assert [one.ledger_id for one in result.indexed] == [BOUND[1]]


def test_a_ledger_that_fails_is_named_and_the_rest_are_read() -> None:
    asked.clear()

    result = index((BOUND[0], UNBOUND, BOUND[1]))

    assert asked == [BOUND[0], UNBOUND, BOUND[1]]
    assert [one.ledger_id for one in result.indexed] == BOUND
    assert result.failed == (UNBOUND,)


def test_a_history_recorded_by_earlier_code_still_replays() -> None:
    """Replay a history recorded from a real run of this workflow.

    Temporal continues an unfinished run by running the workflow's code
    again over the run's recorded history. If the code now takes
    different steps, the replay fails, and so would every run that was
    in progress when the change was deployed
    (docs/ADRs/003-use-cases-under-temporal.md).

    If this test fails, the workflow's steps have changed. Guard the
    change with ``workflow.patched`` first. Only then record a new
    history, by running the tests with UPDATE_HISTORIES=1.
    """
    if os.environ.get("UPDATE_HISTORIES"):
        histories: list[WorkflowHistory] = []
        index(histories=histories)
        HISTORY.write_text(anonymous(histories[0].to_json()))
    recorded = WorkflowHistory.from_json("archive-index", HISTORY.read_text())
    asyncio.run(
        Replayer(
            workflows=[ArchiveIndexWorkflow],
            data_converter=pydantic_data_converter,
            workflow_runner=workflow_runner(),
        ).replay_workflow(recorded)
    )


def test_the_host_s_request_starts_the_workflow_for_one_ledger() -> None:
    """The archive host asks for a ledger to be indexed through
    ``TemporalIndexingRequests``, which knows the workflow only by its
    name. This runs that request against a real worker, to show the two
    agree on the name, the input and the workflow id."""
    asked.clear()

    async def run() -> ArchiveIndexResult:
        async with await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        ) as env:
            queue = f"archive-index-{uuid.uuid4()}"
            where = TemporalAddress(
                env.client.service_client.config.target_host,
                env.client.namespace,
                queue,
            )
            async with Worker(
                env.client,
                task_queue=queue,
                workflows=[ArchiveIndexWorkflow],
                activities=[fake_bound_ledgers, fake_index_archive],
                workflow_runner=workflow_runner(),
            ):
                await asyncio.to_thread(
                    TemporalIndexingRequests(where).request_catch_up, BOUND[0]
                )
                handle = env.client.get_workflow_handle(
                    index_workflow_id(BOUND[0])
                )
                described = await handle.describe()
                assert described.workflow_type == INDEX_WORKFLOW
                result: ArchiveIndexResult = await handle.result(
                    rpc_timeout=None
                )
                return ArchiveIndexResult.model_validate(result)

    result = asyncio.run(run())

    assert asked == [BOUND[0]]
    assert [one.ledger_id for one in result.indexed] == [BOUND[0]]


def test_a_request_that_cannot_reach_temporal_raises_nothing() -> None:
    TemporalIndexingRequests(
        TemporalAddress("127.0.0.1:1", "default", "a-queue")
    ).request_catch_up(BOUND[0])
