"""Tests of the pull request workflow, run by Temporal's test server.

Stand-ins take the place of the evaluation and of the activities. The
last two tests replay recorded histories.
"""

import asyncio
import os
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path

from temporalio import activity, workflow
from temporalio.client import WorkflowHandle, WorkflowHistory
from temporalio.common import WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

with workflow.unsafe.imports_passed_through():
    from bugflow.apps.worker.evaluate_pull_request import (
        workflow_id_for,
    )
    from bugflow.apps.worker.pull_request import (
        CLOSE_SIGNAL,
        COLLECT_AT_CLOSE_ACTIVITY,
        DELIVERY_SIGNAL,
        EVALUATE_WORKFLOW,
        IS_OPEN_ACTIVITY,
        PullRequestWorkflow,
        PullRequestWorkflowInput,
    )
    from bugflow.apps.worker.worker import workflow_runner
    from bugflow.review.dtos.collect_at_close import (
        CollectAtCloseRequest,
        CollectAtCloseResponse,
    )
    from bugflow.review.dtos.evaluate_pull_request import (
        EvaluatePullRequestRequest,
    )
    from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="orchard", repo="pear-tree", number=9)
DEBOUNCE = timedelta(seconds=60)
IDLE_CHECK = timedelta(minutes=10)

forge_says_open = True
asked = 0

evaluations: list[tuple[str, tuple[str, ...]]] = []
unpublished: list[tuple[str, ...]] = []
collected: list[CollectAtCloseRequest] = []


@activity.defn(name="record_evaluation")
async def record_evaluation(request: EvaluatePullRequestRequest) -> None:
    workflow_id = activity.info().workflow_id or ""
    evaluations.append((workflow_id, request.delivery_ids))
    if not request.publish:
        unpublished.append(request.delivery_ids)


@activity.defn(name=COLLECT_AT_CLOSE_ACTIVITY)
async def collect_at_close(
    request: CollectAtCloseRequest,
) -> CollectAtCloseResponse:
    collected.append(request)
    return CollectAtCloseResponse(reactions=0, merged=False, outstanding=0)


@activity.defn(name=IS_OPEN_ACTIVITY)
async def is_open(ref: PullRequestRef) -> bool:
    global asked
    asked += 1
    return forge_says_open


@workflow.defn(name=EVALUATE_WORKFLOW)
class FakeEvaluation:
    @workflow.run
    async def run(self, request: EvaluatePullRequestRequest) -> None:
        if "unfetchable" in request.delivery_ids:
            raise ApplicationError("GitHub returned 404", non_retryable=True)
        await workflow.execute_activity(
            "record_evaluation",
            request,
            start_to_close_timeout=timedelta(seconds=10),
        )


Scenario = Callable[[WorkflowEnvironment, str], Awaitable[None]]


def run(scenario: Scenario) -> None:
    global forge_says_open, asked
    evaluations.clear()
    unpublished.clear()
    collected.clear()
    forge_says_open = True
    asked = 0

    async def main() -> None:
        async with await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        ) as env:
            task_queue = f"test-{uuid.uuid4()}"
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[PullRequestWorkflow, FakeEvaluation],
                activities=[record_evaluation, is_open, collect_at_close],
                workflow_runner=workflow_runner(),
            ):
                await scenario(env, task_queue)

    asyncio.run(main())


async def deliver(
    env: WorkflowEnvironment,
    task_queue: str,
    delivery_id: str,
    evaluations_per_run: int = 20,
) -> WorkflowHandle[PullRequestWorkflow, None]:
    return await env.client.start_workflow(
        PullRequestWorkflow.run,
        PullRequestWorkflowInput(
            ref=REF,
            debounce_seconds=DEBOUNCE.total_seconds(),
            evaluations_per_run=evaluations_per_run,
        ),
        id=workflow_id_for(REF),
        task_queue=task_queue,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        start_signal=DELIVERY_SIGNAL,
        start_signal_args=[delivery_id],
    )


async def evaluated(count: int) -> None:
    for _ in range(400):
        if len(evaluations) >= count:
            return
        await asyncio.sleep(0.025)
    raise AssertionError(f"expected {count} evaluations, saw {evaluations}")


async def close(env: WorkflowEnvironment) -> None:
    handle = env.client.get_workflow_handle(workflow_id_for(REF))
    await handle.signal(CLOSE_SIGNAL, "d-close")
    await handle.result()


async def close_merged(env: WorkflowEnvironment) -> None:
    handle = env.client.get_workflow_handle(workflow_id_for(REF))
    await handle.signal(CLOSE_SIGNAL, args=["d-close", True])
    await handle.result()


def evaluation(delivery_id: str) -> str:
    return f"{workflow_id_for(REF)}/evaluation/{delivery_id}"


def test_a_burst_of_deliveries_is_evaluated_once() -> None:
    async def scenario(env: WorkflowEnvironment, task_queue: str) -> None:
        await deliver(env, task_queue, "d-1")
        await env.sleep(timedelta(seconds=30))
        await deliver(env, task_queue, "d-2")
        await env.sleep(timedelta(seconds=30))
        await deliver(env, task_queue, "d-3")
        await asyncio.sleep(0.2)
        assert evaluations == []

        await env.sleep(DEBOUNCE + timedelta(seconds=1))
        await evaluated(1)
        await close(env)
        assert evaluations == [(evaluation("d-3"), ("d-1", "d-2", "d-3"))]

    run(scenario)


def test_deliveries_further_apart_than_the_debounce_are_evaluated_apart() -> (
    None
):
    async def scenario(env: WorkflowEnvironment, task_queue: str) -> None:
        for n, delivery_id in enumerate(["d-1", "d-2"], start=1):
            await deliver(env, task_queue, delivery_id)
            await env.sleep(DEBOUNCE + timedelta(seconds=1))
            await evaluated(n)
        await close(env)
        assert evaluations == [
            (evaluation("d-1"), ("d-1",)),
            (evaluation("d-2"), ("d-2",)),
        ]

    run(scenario)


def test_closing_ends_the_workflow_without_evaluating_what_is_pending() -> (
    None
):
    async def scenario(env: WorkflowEnvironment, task_queue: str) -> None:
        await deliver(env, task_queue, "d-1")
        await close(env)
        assert evaluations == []

    run(scenario)


def test_a_failed_evaluation_does_not_end_the_workflow() -> None:
    async def scenario(env: WorkflowEnvironment, task_queue: str) -> None:
        await deliver(env, task_queue, "unfetchable")
        await env.sleep(DEBOUNCE + timedelta(seconds=1))
        await deliver(env, task_queue, "d-2")
        await env.sleep(DEBOUNCE + timedelta(seconds=1))
        await evaluated(1)
        await close(env)
        assert evaluations == [(evaluation("d-2"), ("d-2",))]

    run(scenario)


def test_the_workflow_continues_as_new_and_keeps_evaluating() -> None:
    async def scenario(env: WorkflowEnvironment, task_queue: str) -> None:
        first = await deliver(env, task_queue, "d-1", evaluations_per_run=1)
        await env.sleep(DEBOUNCE + timedelta(seconds=1))
        await evaluated(1)
        second = await deliver(env, task_queue, "d-2", evaluations_per_run=1)
        await env.sleep(DEBOUNCE + timedelta(seconds=1))
        await evaluated(2)
        await close(env)
        assert first.result_run_id != second.result_run_id
        assert [ids for _, ids in evaluations] == [("d-1",), ("d-2",)]

    run(scenario)


def test_a_pull_request_closed_behind_its_back_ends_the_workflow() -> None:

    async def scenario(env: WorkflowEnvironment, task_queue: str) -> None:
        global forge_says_open
        handle = await deliver(env, task_queue, "d-1")
        await env.sleep(DEBOUNCE + timedelta(seconds=30))
        await evaluated(1)
        forge_says_open = False
        await env.sleep(IDLE_CHECK + timedelta(seconds=30))
        await asyncio.wait_for(handle.result(), 30)
        assert asked >= 1

    run(scenario)


def test_an_open_pull_request_keeps_waiting() -> None:

    async def scenario(env: WorkflowEnvironment, task_queue: str) -> None:
        await deliver(env, task_queue, "d-1")
        await env.sleep(DEBOUNCE + timedelta(seconds=30))
        await evaluated(1)
        await env.sleep(IDLE_CHECK * 3)
        assert asked >= 1
        handle = env.client.get_workflow_handle(workflow_id_for(REF))
        await handle.signal(DELIVERY_SIGNAL, "d-2")
        await env.sleep(DEBOUNCE + timedelta(seconds=30))
        await evaluated(2)
        await close(env)

    run(scenario)


def test_what_merged_inside_the_debounce_is_evaluated_once_unpublished() -> (
    None
):

    async def scenario(env: WorkflowEnvironment, task_queue: str) -> None:
        await deliver(env, task_queue, "d-1")
        await close_merged(env)
        assert [ids for _, ids in evaluations] == [("d-1", "d-close")]
        assert unpublished == [("d-1", "d-close")]

    run(scenario)


def test_a_merge_with_nothing_pending_is_still_evaluated() -> None:

    async def scenario(env: WorkflowEnvironment, task_queue: str) -> None:
        await deliver(env, task_queue, "d-1")
        await env.sleep(DEBOUNCE + timedelta(seconds=1))
        await evaluated(1)
        await close_merged(env)
        assert [ids for _, ids in evaluations] == [("d-1",), ("d-close",)]
        assert unpublished == [("d-close",)]

    run(scenario)


def test_a_close_collects_the_conversation_once() -> None:

    async def scenario(env: WorkflowEnvironment, task_queue: str) -> None:
        await deliver(env, task_queue, "d-1")
        await close(env)
        assert [c.ref for c in collected] == [REF]
        assert collected[0].correlation.workflow_id == workflow_id_for(REF)

    run(scenario)


def test_a_merge_collects_after_what_merged_is_evaluated() -> None:
    async def scenario(env: WorkflowEnvironment, task_queue: str) -> None:
        await deliver(env, task_queue, "d-1")
        await close_merged(env)
        assert unpublished == [("d-1", "d-close")]
        assert [c.ref for c in collected] == [REF]

    run(scenario)


def test_a_pull_request_found_closed_is_collected_too() -> None:

    async def scenario(env: WorkflowEnvironment, task_queue: str) -> None:
        global forge_says_open
        handle = await deliver(env, task_queue, "d-1")
        await env.sleep(DEBOUNCE + timedelta(seconds=30))
        await evaluated(1)
        forge_says_open = False
        await env.sleep(IDLE_CHECK + timedelta(seconds=30))
        await asyncio.wait_for(handle.result(), 30)
        assert [c.ref for c in collected] == [REF]

    run(scenario)


HISTORY = Path(__file__).parent / "histories" / "pull_request.json"


def test_a_history_recorded_by_earlier_code_still_replays() -> None:
    """Replay a history recorded from a run of this workflow. A change
    that is meant to alter the workflow's steps records it again, by
    running the tests with UPDATE_HISTORIES=1.
    """
    if os.environ.get("UPDATE_HISTORIES"):

        async def scenario(env: WorkflowEnvironment, task_queue: str) -> None:
            await deliver(env, task_queue, "d-1")
            await env.sleep(DEBOUNCE + timedelta(seconds=1))
            await evaluated(1)
            await close(env)
            handle = env.client.get_workflow_handle(workflow_id_for(REF))
            history = await handle.fetch_history()
            HISTORY.parent.mkdir(parents=True, exist_ok=True)
            HISTORY.write_text(anonymous(history.to_json()))

        run(scenario)
    recorded = WorkflowHistory.from_json(
        workflow_id_for(REF), HISTORY.read_text()
    )
    asyncio.run(
        Replayer(
            workflows=[PullRequestWorkflow],
            data_converter=pydantic_data_converter,
            workflow_runner=workflow_runner(),
        ).replay_workflow(recorded)
    )


HISTORY_COLLECTED = HISTORY.with_name("pull_request_collected_at_close.json")


def test_a_history_that_collected_at_close_still_replays() -> None:
    """The same for a run that collected the conversation at its close."""
    if os.environ.get("UPDATE_HISTORIES"):

        async def scenario(env: WorkflowEnvironment, task_queue: str) -> None:
            await deliver(env, task_queue, "d-1")
            await env.sleep(DEBOUNCE + timedelta(seconds=1))
            await evaluated(1)
            await close(env)
            handle = env.client.get_workflow_handle(workflow_id_for(REF))
            history = await handle.fetch_history()
            HISTORY_COLLECTED.write_text(anonymous(history.to_json()))

        run(scenario)
    recorded = WorkflowHistory.from_json(
        workflow_id_for(REF), HISTORY_COLLECTED.read_text()
    )
    asyncio.run(
        Replayer(
            workflows=[PullRequestWorkflow],
            data_converter=pydantic_data_converter,
            workflow_runner=workflow_runner(),
        ).replay_workflow(recorded)
    )


def anonymous(history: str) -> str:
    """Remove the recording machine's name and the paths in stack traces
    from a history before it is saved.
    """
    return re.sub(r'"identity": "[^"]*"', '"identity": "recorded"', history)
