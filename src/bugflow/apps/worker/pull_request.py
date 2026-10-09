"""The workflow that follows one pull request, from its first delivery
until it closes.

A delivery is a message from the forge that something happened to the
pull request. Deliveries reach the workflow as signals.

- An evaluation starts once no delivery has arrived for the debounce
  time. So several pushes close together are evaluated once, as the
  pull request stands after the last of them. Deliveries that arrive
  while an evaluation runs are evaluated after it.
- Each evaluation is a child workflow with an id of its own. If one
  fails, that is logged and this workflow carries on.
- A close signal ends the workflow. If the pull request merged, what
  merged is evaluated once first, with nothing published. Otherwise a
  pull request that merged inside the debounce time would never be
  evaluated.
- The close signal can fail to arrive. So while nothing is happening
  the workflow asks the forge, every ten minutes, whether the pull
  request is still open, and ends if it is not.
- When the pull request closes, its conversation is collected once.
- After a number of evaluations, or when Temporal suggests it, the
  workflow continues as a new run and takes its pending deliveries with
  it. So its history stays small however long the pull request is open.
"""

from datetime import timedelta
from functools import partial

from pydantic import BaseModel, ConfigDict
from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from bugflow.apps.worker.evaluate_pull_request import (
        evaluation_id_for,
    )
    from bugflow.review.dtos.collect_at_close import (
        CollectAtCloseRequest,
        CollectAtCloseResponse,
    )
    from bugflow.review.dtos.evaluate_pull_request import (
        EvaluatePullRequestRequest,
    )
    from bugflow.shared.domain.values.correlation import Correlation
    from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

#: The name of the child workflow that runs one evaluation.
EVALUATE_WORKFLOW = "EvaluatePullRequestWorkflow"
#: The two signals: a delivery arrived, and the pull request closed.
DELIVERY_SIGNAL = "delivery"
CLOSE_SIGNAL = "close"
#: The id of a change: a merged pull request is evaluated once when it
#: closes. A run that closed before the change replays without it.
EVALUATE_ON_MERGE = "evaluate-on-merge"
#: The activity that asks the forge whether the pull request is open.
IS_OPEN_ACTIVITY = "pull_request_is_open"
#: The activity that collects the conversation at the close, and the id
#: of the change that added it.
COLLECT_AT_CLOSE_ACTIVITY = "collect_at_close"
COLLECT_AT_CLOSE = "collect-at-close"
#: How long no delivery must arrive before an evaluation starts.
DEBOUNCE = timedelta(seconds=60)
#: How many evaluations a run makes before it continues as a new run.
EVALUATIONS_PER_RUN = 20
#: How long the workflow waits with nothing happening before it asks
#: the forge whether the pull request is still open.
IDLE_CHECK = timedelta(minutes=10)


class PullRequestWorkflowInput(BaseModel):
    """What the workflow is started with. ``pending`` are deliveries that
    an earlier run received and did not evaluate.
    """

    model_config = ConfigDict(frozen=True)

    ref: PullRequestRef
    debounce_seconds: float = DEBOUNCE.total_seconds()
    idle_check_seconds: float = IDLE_CHECK.total_seconds()
    evaluations_per_run: int = EVALUATIONS_PER_RUN
    pending: tuple[str, ...] = ()


@workflow.defn(name="PullRequestWorkflow")
class PullRequestWorkflow:
    def __init__(self) -> None:
        self._pending: list[str] = []
        self._received = 0
        self._closed = False
        self._merged = False
        self._close_delivery = ""

    @workflow.signal(name=DELIVERY_SIGNAL)
    def delivery(self, delivery_id: str) -> None:
        """Note a delivery. A delivery already pending is not added twice."""
        if delivery_id not in self._pending:
            self._pending.append(delivery_id)
        self._received += 1

    @workflow.signal(name=CLOSE_SIGNAL)
    def close(self, delivery_id: str, merged: bool = False) -> None:
        """Note that the pull request closed. ``merged`` has a default so
        that a close signalled before the argument existed still replays.
        """
        self._closed = True
        self._merged = merged
        self._close_delivery = delivery_id

    @workflow.run
    async def run(self, input: PullRequestWorkflowInput) -> None:
        self._pending = [
            *input.pending,
            *(d for d in self._pending if d not in input.pending),
        ]
        debounce = timedelta(seconds=input.debounce_seconds)
        idle_check = timedelta(seconds=input.idle_check_seconds)
        evaluations = 0
        while True:
            while not await self._something_to_do(idle_check):
                if not await self._still_open(input.ref):
                    await self._collect(input.ref)
                    return
                if workflow.info().is_continue_as_new_suggested():
                    workflow.continue_as_new(
                        input.model_copy(
                            update={"pending": tuple(self._pending)}
                        )
                    )
            if not self._closed:
                await self._quiet_for(debounce)
            if self._closed:
                await self._judge_what_merged(input.ref)
                await self._collect(input.ref)
                return

            batch = tuple(self._pending)
            self._pending.clear()
            await self._evaluate(input.ref, batch)

            evaluations += 1
            if (
                evaluations >= input.evaluations_per_run
                or workflow.info().is_continue_as_new_suggested()
            ) and not self._closed:
                workflow.continue_as_new(
                    input.model_copy(update={"pending": tuple(self._pending)})
                )

    async def _evaluate(
        self,
        ref: PullRequestRef,
        batch: tuple[str, ...],
        publish: bool = True,
    ) -> None:
        """Run one evaluation of these deliveries as a child workflow. A
        failure is logged and not raised.
        """
        try:
            await workflow.execute_child_workflow(
                EVALUATE_WORKFLOW,
                EvaluatePullRequestRequest(
                    ref=ref, delivery_ids=batch, publish=publish
                ),
                id=evaluation_id_for(ref, batch[-1]),
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                execution_timeout=timedelta(minutes=30),
            )
        except ChildWorkflowError as exc:
            workflow.logger.warning(
                "evaluation of %s for deliveries %s failed: %s",
                ref,
                ", ".join(batch),
                exc.cause or exc,
            )

    async def _judge_what_merged(self, ref: PullRequestRef) -> None:
        """Evaluate a merged pull request once, publishing nothing. This is
        done even when no delivery is pending, because a delivery may have
        been lost.
        """
        if not self._merged or not workflow.patched(EVALUATE_ON_MERGE):
            return
        batch = (*self._pending, self._close_delivery)
        self._pending.clear()
        await self._evaluate(ref, batch, publish=False)

    async def _collect(self, ref: PullRequestRef) -> None:
        """Collect the conversation now that the pull request has closed. A
        failure is logged and not raised.
        """
        if not workflow.patched(COLLECT_AT_CLOSE):
            return
        info = workflow.info()
        try:
            await workflow.execute_activity(
                COLLECT_AT_CLOSE_ACTIVITY,
                CollectAtCloseRequest(
                    ref=ref,
                    correlation=Correlation(
                        workflow_id=info.workflow_id, run_id=info.run_id
                    ),
                ),
                result_type=CollectAtCloseResponse,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=5),
            )
        except ActivityError as exc:
            workflow.logger.warning(
                "collecting %s at its close failed: %s", ref, exc.cause or exc
            )

    async def _something_to_do(self, idle_check: timedelta) -> bool:
        """Wait for a delivery or a close, for at most ``idle_check``.
        Returns False if neither came.
        """
        try:
            await workflow.wait_condition(
                lambda: bool(self._pending) or self._closed,
                timeout=idle_check,
            )
        except TimeoutError:
            return False
        return True

    async def _still_open(self, ref: PullRequestRef) -> bool:
        """Ask the forge whether the pull request is open. If it is not,
        the workflow treats it as closed.
        """
        if await workflow.execute_activity(
            IS_OPEN_ACTIVITY,
            ref,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        ):
            return True
        self._closed = True
        return False

    async def _quiet_for(self, debounce: timedelta) -> None:
        """Return once no delivery has arrived for ``debounce``, or as soon
        as the pull request closes.
        """
        while True:
            try:
                await workflow.wait_condition(
                    partial(self._changed_since, self._received),
                    timeout=debounce,
                )
            except TimeoutError:
                return
            if self._closed:
                return

    def _changed_since(self, received: int) -> bool:
        """Whether a delivery has arrived since ``received`` of them had, or
        the pull request has closed.
        """
        return self._received != received or self._closed
