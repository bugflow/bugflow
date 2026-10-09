"""Tests of the stocktake workflow, run by Temporal's test server.

Stand-ins take the place of the activities. One test replays a recorded
history.
"""

import asyncio
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from temporalio import activity, workflow
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

with workflow.unsafe.imports_passed_through():
    from bugflow.apps.worker.evaluate_pull_request import (
        REVIEW_STOP_ACTIVITY,
        judge_task_queue,
    )
    from bugflow.apps.worker.stocktake import (
        REVIEW_DEADLINE,
        STOCKTAKE_COLLECT_ACTIVITY,
        STOCKTAKE_DISPATCH_ACTIVITY,
        STOCKTAKE_GRADE_ACTIVITY,
        STOCKTAKE_REVIEWERS_ACTIVITY,
        STOCKTAKE_WAIT_ACTIVITY,
        TAKE_STOCK_ACTIVITY,
        StocktakeWorkflow,
    )
    from bugflow.apps.worker.worker import workflow_runner
    from bugflow.review.domain.models.delegation import Handle, Run
    from bugflow.review.dtos.review_range import (
        CollectRangeReviewRequest,
        CollectRangeReviewResponse,
        DispatchRangeReviewRequest,
        DispatchRangeReviewResponse,
        GradeRangeReviewRequest,
        GradeRangeReviewResponse,
        WaitRangeReviewRequest,
        WaitRangeReviewResponse,
    )
    from bugflow.review.dtos.take_stock import (
        TakeStockRequest,
        TakeStockResponse,
    )
    from bugflow.shared.domain.values.correlation import Correlation

SUNDAY = datetime(2030, 9, 27, 13, 30, tzinfo=UTC)
asked: list[TakeStockRequest] = []


dispatched: list[DispatchRangeReviewRequest] = []
graded: list[GradeRangeReviewRequest] = []
stopped: list[Handle] = []
waited_for: list[float] = []
worth = True
running = False
answers: list[str] = []
collected_at: list[datetime] = []


@activity.defn(name=TAKE_STOCK_ACTIVITY)
async def fake_take_stock(request: TakeStockRequest) -> TakeStockResponse:
    asked.append(request)
    return TakeStockResponse(
        since=None,
        until=SUNDAY,
        merged=2 if worth else 0,
        worth_taking=worth,
        base_sha="b" * 40,
        head_sha="a" * 40 if worth else None,
    )


@activity.defn(name=STOCKTAKE_REVIEWERS_ACTIVITY)
async def fake_reviewers(layer: str, forge: str, repo: str) -> list[str]:
    return ["safety"]


@activity.defn(name=STOCKTAKE_DISPATCH_ACTIVITY)
async def fake_dispatch(
    request: DispatchRangeReviewRequest,
) -> DispatchRangeReviewResponse:
    dispatched.append(request)
    return DispatchRangeReviewResponse(
        handle=Handle(
            runner="managed-agent", fingerprint="r-1", remote_id="ses-1"
        )
    )


@activity.defn(name=STOCKTAKE_WAIT_ACTIVITY)
async def fake_wait(
    request: WaitRangeReviewRequest,
) -> WaitRangeReviewResponse:
    waited_for.append(request.patience)
    return WaitRangeReviewResponse(ready=True)


@activity.defn(name=STOCKTAKE_COLLECT_ACTIVITY)
async def fake_collect(
    request: CollectRangeReviewRequest,
) -> CollectRangeReviewResponse:
    collected_at.append(activity.info().scheduled_time)
    if answers:
        outcome = answers.pop(0)
        return CollectRangeReviewResponse(
            run=Run(
                outcome=outcome,  # type: ignore[arg-type]
                artifact={"write_up": "Read it."},
            ),
            reason="asked again" if outcome == "running" else "",
        )
    if running:
        return CollectRangeReviewResponse(
            run=Run(outcome="running"), reason="still going"
        )
    return CollectRangeReviewResponse(
        run=Run(outcome="completed", artifact={"write_up": "Read it."})
    )


@activity.defn(name=REVIEW_STOP_ACTIVITY)
async def fake_stop(handle: Handle) -> None:
    stopped.append(handle)


@activity.defn(name=STOCKTAKE_GRADE_ACTIVITY)
async def fake_grade(
    request: GradeRangeReviewRequest,
) -> GradeRangeReviewResponse:
    graded.append(request)
    return GradeRangeReviewResponse(status="warn", detail="one thing")


REQUEST = TakeStockRequest(
    forge="github",
    repo="orchard/pear-tree",
    layer="weekly",
    correlation=Correlation(
        workflow_id="stocktake/github/orchard/pear-tree/weekly", run_id="s-1"
    ),
)


def take_stock(
    histories: list[WorkflowHistory] | None = None,
    signals: int = 0,
) -> TakeStockResponse:
    async def run() -> TakeStockResponse:
        async with await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        ) as env:
            queue = f"stocktake-{uuid.uuid4()}"
            async with (
                Worker(
                    env.client,
                    task_queue=queue,
                    workflows=[StocktakeWorkflow],
                    activities=[
                        fake_take_stock,
                        fake_reviewers,
                        fake_dispatch,
                        fake_wait,
                        fake_collect,
                        fake_grade,
                    ],
                    workflow_runner=workflow_runner(),
                ),
                Worker(
                    env.client,
                    task_queue=judge_task_queue(queue),
                    activities=[fake_stop],
                ),
            ):
                handle = await env.client.start_workflow(
                    StocktakeWorkflow.run,
                    REQUEST,
                    id=f"stocktake-{uuid.uuid4()}",
                    task_queue=queue,
                )
                for _ in range(signals):
                    await handle.signal(
                        StocktakeWorkflow.review_complete,
                        args=["safety", "ses-1"],
                    )
                taken: TakeStockResponse = await handle.result()
                if histories is not None:
                    histories.append(await handle.fetch_history())
                return taken

    return asyncio.run(run())


def test_the_week_is_dispatched_read_and_graded() -> None:
    asked.clear()
    dispatched.clear()
    graded.clear()
    taken = take_stock()
    assert (taken.merged, taken.worth_taking) == (2, True)
    assert [one.layer for one in asked] == ["weekly"]
    assert [one.agent_id for one in dispatched] == ["safety"]
    assert dispatched[0].base_sha == "b" * 40
    assert [one.agent_id for one in graded] == ["safety"]


def test_a_run_still_going_at_the_deadline_is_stopped() -> None:
    global running
    stopped.clear()
    graded.clear()
    running = True
    try:
        take_stock()
    finally:
        running = False
    assert [one.remote_id for one in stopped] == ["ses-1"]
    assert graded == []


def test_a_run_that_answers_is_not_stopped() -> None:
    stopped.clear()
    take_stock()
    assert stopped == []


def test_a_quiet_week_asks_nobody_anything() -> None:
    global worth
    dispatched.clear()
    worth = False
    try:
        taken = take_stock()
    finally:
        worth = True
    assert not taken.worth_taking
    assert dispatched == []


HISTORY = Path(__file__).parent / "histories" / "stocktake.json"


def test_a_run_that_answered_out_of_shape_is_graded() -> None:
    graded.clear()
    answers[:] = ["malformed"]
    take_stock()
    assert len(graded) == 1


def test_a_run_asked_again_is_waited_for_again() -> None:
    graded.clear()
    waited_for.clear()
    answers[:] = ["running", "completed"]
    take_stock(signals=1)
    assert len(waited_for) == 2
    assert len(graded) == 1


def test_the_deadline_is_what_is_left_of_it() -> None:
    waited_for.clear()
    answers[:] = ["running", "completed"]
    take_stock(signals=1)
    assert waited_for == sorted(waited_for, reverse=True)
    assert max(waited_for) <= REVIEW_DEADLINE.total_seconds()


def test_a_history_recorded_by_earlier_code_still_replays() -> None:
    """Replay a history recorded from a run of this workflow. A change
    that is meant to alter the workflow's steps records it again, by
    running the tests with UPDATE_HISTORIES=1.
    """
    if os.environ.get("UPDATE_HISTORIES"):
        histories: list[WorkflowHistory] = []
        take_stock(histories)
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(anonymous(histories[0].to_json()))
    recorded = WorkflowHistory.from_json("stocktake", HISTORY.read_text())
    asyncio.run(
        Replayer(
            workflows=[StocktakeWorkflow],
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


def test_each_run_records_against_its_own_execution() -> None:
    asked.clear()
    dispatched.clear()
    take_stock()
    first = asked[0].correlation
    take_stock()
    second = asked[-1].correlation

    assert first.run_id != REQUEST.correlation.run_id
    assert first.run_id != second.run_id
    assert [one.correlation for one in dispatched] == [first, second]
