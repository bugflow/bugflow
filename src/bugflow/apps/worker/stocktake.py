"""The workflow that runs one stocktake.

A schedule starts it, once for each layer and each watched repository.
It works out the range the layer has not yet covered and leaves the
layer's mark. If nothing merged in the range it ends there, so a quiet
period costs nothing.

Otherwise each reviewer the layer has reviews the range, one after
another: its run is dispatched, waited for, collected and graded. A run
still going at the deadline is stopped.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from bugflow.apps.worker.evaluate_pull_request import (
        A_WAIT_HAS_A_NAME,
        REVIEW_STOP_ACTIVITY,
        judge_task_queue,
        wait_id,
    )
    from bugflow.review.domain.models.delegation import Handle
    from bugflow.review.domain.models.grading import ANSWERED
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

#: The activities: work out the range and leave the mark; list the
#: reviewers the layer has; and the four steps of one review.
TAKE_STOCK_ACTIVITY = "take_stock"
STOCKTAKE_REVIEWERS_ACTIVITY = "stocktake_reviewers"
STOCKTAKE_DISPATCH_ACTIVITY = "stocktake_dispatch"
STOCKTAKE_WAIT_ACTIVITY = "stocktake_wait"
STOCKTAKE_COLLECT_ACTIVITY = "stocktake_collect"
STOCKTAKE_GRADE_ACTIVITY = "stocktake_grade"

#: The id of a change: the workflow goes on waiting only while the run
#: is still running. Before, a run that had ended without answering was
#: asked about again and again until the deadline.
WAIT_ONLY_WHILE_RUNNING = "wait-only-while-running"

#: How long a review may take before the stocktake gives up on it.
REVIEW_DEADLINE = timedelta(hours=2)

#: The id of a change: after a run is asked for another answer, the
#: workflow waits for its next completion, not for any completion. The
#: same change has a run whose answer did not match the shape graded,
#: since its write-up is prose like any other.
WAIT_FOR_THE_NEXT = "stocktake-wait-for-the-next-completion"
#: The id of a change: a run still going at the deadline is stopped.
STOP_AT_DEADLINE = "stocktake-stop-at-deadline"

#: How long the older ways of waiting wait between collecting.
POLL = timedelta(minutes=10)

#: The signal that tells the workflow a runner has finished a run. It
#: has the same name as the evaluation workflow's, because the same
#: route sends both.
REVIEW_COMPLETE_SIGNAL = "review_complete"

#: The id of a change: the workflow waits for a completion signal with
#: a timer beside it. Before, it slept between collecting.
TOLD_RATHER_THAN_ASKING = "told-rather-than-asking"

#: The id of a change: a wait is an activity. Before, it was a signal
#: with a timer of the workflow's beside it.
THE_PORT_WAITS = "the-port-holds-the-wait"


@workflow.defn(name="StocktakeWorkflow")
class StocktakeWorkflow:
    def __init__(self) -> None:
        self._completed: dict[str, str] = {}
        self._told: dict[str, int] = {}
        self._waits: dict[str, int] = {}

    @workflow.signal(name=REVIEW_COMPLETE_SIGNAL)
    def review_complete(self, agent_id: str, remote_id: str) -> None:
        """Note that a runner has finished a run for an agent. The workflow
        waits on what is noted, so a signal that arrives before the wait
        starts is not missed.
        """
        self._completed[agent_id] = remote_id
        self._told[agent_id] = self._told.get(agent_id, 0) + 1

    @workflow.run
    async def run(self, request: TakeStockRequest) -> TakeStockResponse:
        # The request's workflow run is replaced by this run's own. A
        # schedule sends the same request every time it fires. If the
        # run in it were used, every stocktake would record its facts
        # under the same ids, and the journal keeps only the first
        # entry with an id.
        info = workflow.info()
        request = request.model_copy(
            update={
                "correlation": Correlation(
                    workflow_id=info.workflow_id, run_id=info.run_id
                )
            }
        )
        taken: TakeStockResponse = await workflow.execute_activity(
            TAKE_STOCK_ACTIVITY,
            request,
            result_type=TakeStockResponse,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not taken.worth_taking or taken.head_sha is None:
            return taken
        for agent_id in await self._reviewers(
            request.layer, request.forge, request.repo
        ):
            await self._read_the_week(request, taken, agent_id)
        return taken

    async def _reviewers(self, layer: str, forge: str, repo: str) -> list[str]:
        """The agent ids of the reviewers the layer has for the repository."""
        held: list[str] = await workflow.execute_activity(
            STOCKTAKE_REVIEWERS_ACTIVITY,
            args=[layer, forge, repo],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return held

    async def _wait_for(
        self,
        request: TakeStockRequest,
        handle: Handle,
        agent: str,
        head: str,
        patience: timedelta,
    ) -> bool:
        """Run the wait activity once, for at most ``patience``.

        The activity is allowed a minute more than ``patience``, so that
        the runner's adapter is what gives up and the answer is "not
        ready".
        """
        turn = self._waits.get(agent, 0) + 1
        self._waits[agent] = turn
        named: str | None = (
            wait_id(agent, handle.remote_id, turn)
            if workflow.patched(A_WAIT_HAS_A_NAME)
            else None
        )
        waited: WaitRangeReviewResponse = await workflow.execute_activity(
            STOCKTAKE_WAIT_ACTIVITY,
            WaitRangeReviewRequest(
                forge=request.forge,
                repo=request.repo,
                layer=request.layer,
                agent_id=agent,
                head_sha=head,
                handle=handle,
                correlation=request.correlation,
                patience=patience.total_seconds(),
            ),
            result_type=WaitRangeReviewResponse,
            schedule_to_close_timeout=patience + timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=1),
            activity_id=named,
        )
        return bool(waited.ready)

    async def _finished_or(
        self,
        agent: str,
        remote_id: str,
        patience: timedelta,
        after: int | None = None,
    ) -> None:
        """The older way to wait: for a completion signal for this run, or
        for ``patience`` to pass. With ``after`` given, only a completion
        later than that many counts.
        """
        try:
            await workflow.wait_condition(
                lambda: (
                    self._completed.get(agent) == remote_id
                    and (after is None or self._told.get(agent, 0) > after)
                ),
                timeout=patience,
            )
        except TimeoutError:
            return

    @staticmethod
    def _answered(seen: int | None) -> tuple[str, ...]:
        """The outcomes whose write-up is graded. On a run from before
        ``WAIT_FOR_THE_NEXT`` that is only "completed".
        """
        return ANSWERED if seen is not None else ("completed",)

    async def _read_the_week(
        self, request: TakeStockRequest, taken: TakeStockResponse, agent: str
    ) -> None:
        """One reviewer's review of the range: dispatch, wait, collect and
        grade.
        """
        head = taken.head_sha or ""
        dispatched: DispatchRangeReviewResponse = (
            await workflow.execute_activity(
                STOCKTAKE_DISPATCH_ACTIVITY,
                DispatchRangeReviewRequest(
                    forge=request.forge,
                    repo=request.repo,
                    layer=request.layer,
                    agent_id=agent,
                    instructions="",
                    base_sha=taken.base_sha,
                    head_sha=head,
                    budget=None,
                    correlation=request.correlation,
                ),
                result_type=DispatchRangeReviewResponse,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        )
        if dispatched.handle is None:
            return
        waited = timedelta()
        # How many completions had arrived when the run was last
        # collected, for waiting for the next one. None on a run from
        # before that change.
        seen = 0 if workflow.patched(WAIT_FOR_THE_NEXT) else None
        while waited < REVIEW_DEADLINE:
            # Three ways to wait, the newest first. A run keeps the
            # way it started with.
            if workflow.patched(THE_PORT_WAITS):
                left = REVIEW_DEADLINE - waited
                ready = await self._wait_for(
                    request, dispatched.handle, agent, head, left
                )
                waited = REVIEW_DEADLINE if not ready else waited + POLL
            elif workflow.patched(TOLD_RATHER_THAN_ASKING):
                await self._finished_or(
                    agent, dispatched.handle.remote_id, POLL, after=seen
                )
                if seen is not None:
                    seen = self._told.get(agent, 0)
                waited += POLL
            else:
                await workflow.sleep(POLL)
                waited += POLL
            collected: CollectRangeReviewResponse = (
                await workflow.execute_activity(
                    STOCKTAKE_COLLECT_ACTIVITY,
                    CollectRangeReviewRequest(
                        forge=request.forge,
                        repo=request.repo,
                        layer=request.layer,
                        agent_id=agent,
                        head_sha=head,
                        handle=dispatched.handle,
                        correlation=request.correlation,
                    ),
                    result_type=CollectRangeReviewResponse,
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            )
            if collected.run is None:
                return
            if workflow.patched(WAIT_ONLY_WHILE_RUNNING):
                if collected.run.outcome == "running":
                    continue
                if collected.run.outcome not in self._answered(seen):
                    return
            if collected.run.outcome in self._answered(seen):
                await workflow.execute_activity(
                    STOCKTAKE_GRADE_ACTIVITY,
                    GradeRangeReviewRequest(
                        forge=request.forge,
                        repo=request.repo,
                        layer=request.layer,
                        agent_id=agent,
                        head_sha=head,
                        run=collected.run,
                        correlation=request.correlation,
                    ),
                    result_type=GradeRangeReviewResponse,
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                return
        if workflow.patched(STOP_AT_DEADLINE):
            await workflow.execute_activity(
                REVIEW_STOP_ACTIVITY,
                dispatched.handle,
                start_to_close_timeout=timedelta(minutes=2),
                task_queue=judge_task_queue(workflow.info().task_queue),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
