"""Tests of the backfill workflow, run by Temporal's test server.

Stand-ins take the place of the evaluation and of the activities. One
test replays a recorded history.
"""

import asyncio
import os
import re
import uuid
from datetime import timedelta
from pathlib import Path

from temporalio import activity, workflow
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

with workflow.unsafe.imports_passed_through():
    from bugflow.apps.worker.backfill import (
        EVALUATE_WORKFLOW,
        LIST_BACKFILL_PAGE_ACTIVITY,
        OUT_OF_ROOM_ACTIVITY,
        BackfillInput,
        BackfillProgress,
        BackfillWorkflow,
    )
    from bugflow.apps.worker.worker import workflow_runner
    from bugflow.review.dtos.evaluate_pull_request import (
        EvaluatePullRequestRequest,
    )
    from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
    from bugflow.work.dtos.list_backfill_page import (
        BackfillPullRequest,
        ListBackfillPageRequest,
        ListBackfillPageResponse,
    )

FAILING = 3


def pull(number: int) -> BackfillPullRequest:
    return BackfillPullRequest(
        ref=PullRequestRef(owner="orchard", repo="pear-tree", number=number),
        head_sha=f"{number:040d}",
    )


PAGES = {
    1: ListBackfillPageResponse(
        pulls=(pull(1), pull(2)), already_observed=0, last=False
    ),
    2: ListBackfillPageResponse(
        pulls=(pull(FAILING),), already_observed=4, last=True
    ),
}

pages_listed: list[int] = []
evaluated: list[tuple[str, EvaluatePullRequestRequest]] = []


no_room = ""


@activity.defn(name=OUT_OF_ROOM_ACTIVITY)
async def fake_room(repository: str) -> str:
    return no_room


@activity.defn(name=LIST_BACKFILL_PAGE_ACTIVITY)
async def fake_list(
    request: ListBackfillPageRequest,
) -> ListBackfillPageResponse:
    pages_listed.append(request.page)
    return PAGES[request.page]


@activity.defn(name="record_backfill_evaluation")
async def record(request: EvaluatePullRequestRequest) -> None:
    evaluated.append((activity.info().workflow_id or "", request))


@workflow.defn(name=EVALUATE_WORKFLOW)
class FakeEvaluation:
    @workflow.run
    async def run(self, request: EvaluatePullRequestRequest) -> None:
        await workflow.execute_activity(
            "record_backfill_evaluation",
            request,
            start_to_close_timeout=timedelta(seconds=10),
        )
        if request.ref.number == FAILING:
            raise ApplicationError("GitHub returned 404", non_retryable=True)


def backfill_twice(
    histories: list[WorkflowHistory] | None = None,
) -> tuple[BackfillProgress, BackfillProgress]:
    pages_listed.clear()
    evaluated.clear()

    async def main() -> tuple[BackfillProgress, BackfillProgress]:
        async with await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        ) as env:
            task_queue = f"test-{uuid.uuid4()}"
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[BackfillWorkflow, FakeEvaluation],
                activities=[fake_list, record, fake_room],
                workflow_runner=workflow_runner(),
            ):
                results = []
                for _ in range(2):
                    handle = await env.client.start_workflow(
                        BackfillWorkflow.run,
                        BackfillInput(repository="orchard/pear-tree"),
                        id=f"backfill-{uuid.uuid4()}",
                        task_queue=task_queue,
                    )
                    results.append(await handle.result())
                    if histories is not None:
                        histories.append(await handle.fetch_history())
                return results[0], results[1]

    return asyncio.run(main())


def test_a_backfill_evaluates_every_page_and_then_skips_what_it_did() -> None:
    first, second = backfill_twice()

    assert pages_listed == [1, 2, 1, 2]
    assert (first.evaluated, first.already_evaluated, first.failed) == (
        2,
        4,
        1,
    )
    assert first.done and first.page == 2
    assert (second.evaluated, second.already_evaluated, second.failed) == (
        0,
        6,
        1,
    )
    numbers = [request.ref.number for _, request in evaluated]
    assert numbers == [1, 2, FAILING, FAILING]


def test_a_backfill_publishes_nothing_calls_no_judge_and_names_the_head() -> (
    None
):
    backfill_twice()
    workflow_id, request = evaluated[0]
    assert (request.publish, request.use_judge) == (False, False)
    assert workflow_id == (
        "pr/github/orchard/pear-tree/1/evaluation/backfill-" + f"{1:040d}"
    )


HISTORY = Path(__file__).parent / "histories" / "backfill.json"


def test_a_history_recorded_by_earlier_code_still_replays() -> None:
    """Replay a history recorded from a run of this workflow. A change
    that is meant to alter the workflow's steps records it again, by
    running the tests with UPDATE_HISTORIES=1.
    """
    if os.environ.get("UPDATE_HISTORIES"):
        histories: list[WorkflowHistory] = []
        backfill_twice(histories)
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(anonymous(histories[0].to_json()))
    recorded = WorkflowHistory.from_json("backfill", HISTORY.read_text())
    asyncio.run(
        Replayer(
            workflows=[BackfillWorkflow],
            data_converter=pydantic_data_converter,
            workflow_runner=workflow_runner(),
        ).replay_workflow(recorded)
    )


def anonymous(history: str) -> str:
    """Remove the recording machine's name and the paths in stack traces
    from a history before it is saved.
    """
    history = re.sub(
        r'"stackTrace": "(?:[^"\\]|\\.)*"', '"stackTrace": ""', history
    )
    return re.sub(r'"identity": "[^"]*"', '"identity": "recorded"', history)


def test_a_backfill_stops_when_an_allowance_has_none_left() -> None:
    global no_room
    no_room = "everything is allowed $150.00 per week and has spent $150.00"
    try:
        first, _ = backfill_twice()
    finally:
        no_room = ""
    assert evaluated == []
    assert first.evaluated == 0
    assert "allowed $150.00 per week" in first.stopped
