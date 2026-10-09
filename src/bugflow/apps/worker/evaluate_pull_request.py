"""The evaluation of one pull request, as a Temporal workflow.

The order of an evaluation's steps is decided by
``EvaluatePullRequestUseCase``. This module is the wrapping that lets
Temporal run it. The use case calls its steps through interfaces. Here
each interface is given a proxy: an object with the interface's methods,
where each method asks Temporal to run an activity. So everything that
reaches outside the process still happens in an activity, each answer
is recorded in the workflow's history, and a replay never asks a model
again.

The pull request is stored by the first activity, and the other
activities are given a reference to it. So the history does not grow
with the size of the pull request.

Activities are named here and not defined here. A worker registers an
implementation under each name.
"""

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from bugflow.forge.dtos.observe_pull_request import (
        ObservePullRequestRequest,
        ObservePullRequestResponse,
    )
    from bugflow.review.domain.errors import ReviewIncompleteError
    from bugflow.review.domain.models.corpus import Corpus
    from bugflow.review.domain.models.delegation import Handle
    from bugflow.review.domain.models.doctrine import DoctrineText
    from bugflow.review.domain.models.evaluation import (
        Answerable,
        Assessed,
        Dispatched,
        Observation,
        Publication,
        Published,
        ReviewAsked,
        Reviewed,
    )
    from bugflow.review.domain.models.submission import SubmissionRef
    from bugflow.review.dtos.assess_policy import (
        AssessPolicyRequest,
        AssessPolicyResponse,
    )
    from bugflow.review.dtos.evaluate_pull_request import (
        EvaluatePullRequestRequest,
        EvaluatePullRequestResponse,
    )
    from bugflow.review.dtos.publish_findings import (
        PublishFindingsRequest,
        PublishFindingsResponse,
    )
    from bugflow.review.dtos.review_with_agent import (
        DispatchedReview,
        ReviewAgentActivityRequest,
        ReviewAgentActivityResponse,
        ReviewCollectActivityRequest,
    )
    from bugflow.review.dtos.wait_review import (
        WaitReviewRequest,
        WaitReviewResponse,
    )
    from bugflow.review.usecases.evaluate_pull_request import (
        EvaluatePullRequestUseCase,
    )
    from bugflow.shared.domain.values.correlation import Correlation
    from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

#: The name the workflow is registered under.
EVALUATE_WORKFLOW = "EvaluatePullRequestWorkflow"
#: Names of activities that older runs called. Nothing here calls them
#: now. A worker still registers them while such a run may be going.
JUDGE_ACTIVITY = "judge_pull_request"
CHECK_ACTIVITY = "check_pull_request"
JUDGE_POLICIES_ACTIVITY = "judge_policies"
#: The activity that lists the policies a repository is reviewed for,
#: and the one that answers a policy.
POLICIES_ACTIVITY = "review_policies"
ASSESS_ACTIVITY = "assess_policy"

#: The id of a change: each class of model has a task queue of its own.
#: No run is left from before it.
A_QUEUE_FOR_EACH_CLASS = "a-queue-for-each-model-class"
#: The activity that lists the installed checkout agents, and the four
#: for the steps of one agent's review: start it, wait for it, stop it,
#: and read and grade it.
REVIEW_AGENTS_ACTIVITY = "review_agents"
REVIEW_DISPATCH_ACTIVITY = "review_dispatch"
REVIEW_WAIT_ACTIVITY = "review_wait"
REVIEW_STOP_ACTIVITY = "review_stop"
REVIEW_COLLECT_ACTIVITY = "review_collect"
#: The signal that tells the workflow a runner has finished a run. Its
#: arguments are the agent id and the runner's name for the work.
REVIEW_COMPLETE_SIGNAL = "review_complete"

#: How long a review may take before the workflow ends it.
REVIEW_DEADLINE = timedelta(hours=1)

#: The id of a change: a review that was asked for another answer is
#: waited for and collected again, within its deadline.
ASK_AGAIN = "evaluation-asks-a-review-again"

#: The start of the activity id given to each wait, so that whatever
#: learns a run has finished can find the wait and end it.
WAIT_ID_PREFIX = "wait-"

#: The id of a change: each wait has an activity id of its own. A run
#: from before the change keeps waits with no such id.
A_WAIT_HAS_A_NAME = "a-wait-has-a-name"

#: The id of a change: a wait is an activity. Before, the workflow
#: waited for a signal with a timer beside it. The use case uses the
#: same id for the wait it makes.
THE_PORT_WAITS = "the-port-holds-the-wait"
PUBLISH_ACTIVITY = "publish_findings"

#: What is added to a task queue's name to name the queue that
#: activities which call a model run on. A worker puts a rate limit on
#: that queue, so every worker shares one limit.
JUDGE_TASK_QUEUE_SUFFIX = "-judge"


def judge_task_queue(task_queue: str) -> str:
    """The name of the rate-limited queue beside a task queue."""
    return f"{task_queue}{JUDGE_TASK_QUEUE_SUFFIX}"


def wait_id(agent_id: str, remote_id: str, turn: int) -> str:
    """The activity id of one wait for a run.

    A run may be waited for more than once, so the waits are
    numbered by ``turn``.
    """
    return f"{WAIT_ID_PREFIX}{agent_id}-{remote_id}-{turn}"


def waits_of(
    open_activities: Iterable[str], agent_id: str, remote_id: str
) -> list[str]:
    """Pick out, from a workflow's open activities, the waits for one
    agent's run.

    Two agents may review one pull request, so a completion for one
    run must end only that run's wait.
    """
    prefix = f"{WAIT_ID_PREFIX}{agent_id}-{remote_id}-"
    return [one for one in open_activities if one.startswith(prefix)]


def queue_for(model_class: str, task_queue: str) -> str:
    """The task queue a policy's answer runs on.

    Each class of model has a queue of its own, because a rate limit
    protects one model's quota. A policy answered without a model, which
    has an empty class, runs on the ordinary queue.
    """
    if not model_class:
        return task_queue
    return f"{judge_task_queue(task_queue)}-{model_class}"


#: How many times an activity is tried.
JUDGE_MAX_ATTEMPTS = 3
PUBLISH_MAX_ATTEMPTS = 5


def workflow_id_for(ref: PullRequestRef) -> str:
    """The id of a pull request's long-lived workflow."""
    return f"pr/{ref.forge}/{ref.owner}/{ref.repo}/{ref.number}"


def evaluation_id_for(ref: PullRequestRef, key: str) -> str:
    """The id of one evaluation of a pull request. ``key`` is the latest
    forge delivery the evaluation answers, or any unique text for an
    evaluation started by hand.
    """
    return f"{workflow_id_for(ref)}/evaluation/{key}"


def patient(attempts: int) -> RetryPolicy:
    """The retry policy for an activity that reads from a forge or writes
    to one.
    """
    return RetryPolicy(
        initial_interval=timedelta(seconds=2),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(minutes=2),
        maximum_attempts=attempts,
    )


class WorkflowExecution:
    """Answers the use case's questions about the workflow run it is in,
    from Temporal.
    """

    def correlation(self) -> Correlation:
        info = workflow.info()
        return Correlation(workflow_id=info.workflow_id, run_id=info.run_id)

    def changed(self, change_id: str) -> bool:
        return workflow.patched(change_id)

    def settled(self, change_id: str) -> None:
        workflow.deprecate_patch(change_id)


class WorkflowAssessment:
    """The proxy for answering policies. Each method runs an activity."""

    async def policies(self, forge: str, repo: str) -> list[Answerable]:
        policies: list[Answerable] = await workflow.execute_activity(
            POLICIES_ACTIVITY,
            args=[forge, repo],
            result_type=list[Answerable],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return policies

    async def assess(
        self,
        policy: Answerable,
        submission: SubmissionRef,
        corpus: Corpus,
        correlation: Correlation,
        head_sha: str | None = None,
    ) -> Assessed:
        return await self._answer(
            AssessPolicyRequest(
                policy_id=policy.policy_id,
                snapshot=submission,
                corpus=corpus,
                correlation=correlation,
                head_sha=head_sha,
            ),
            queue_for(policy.model_class, workflow.info().task_queue),
        )

    async def unjudged(
        self,
        submission: SubmissionRef,
        corpus: Corpus,
        correlation: Correlation,
        head_sha: str | None = None,
    ) -> Assessed:
        return await self._answer(
            AssessPolicyRequest(
                policy_id=None,
                snapshot=submission,
                corpus=corpus,
                correlation=correlation,
                use_judge=False,
                head_sha=head_sha,
            ),
            judge_task_queue(workflow.info().task_queue),
        )

    async def _answer(
        self, request: AssessPolicyRequest, task_queue: str
    ) -> Assessed:
        answered: AssessPolicyResponse = await workflow.execute_activity(
            ASSESS_ACTIVITY,
            request,
            result_type=AssessPolicyResponse,
            task_queue=task_queue,
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=10),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(minutes=2),
                maximum_attempts=JUDGE_MAX_ATTEMPTS,
            ),
        )
        return Assessed(
            findings=answered.findings,
            status=answered.status,
            unavailable=answered.unavailable,
            answered=answered.answered,
        )


def _asking(asked: ReviewAsked) -> ReviewAgentActivityRequest:
    """The activity request for one reviewer's review."""
    return ReviewAgentActivityRequest(
        ref=asked.ref,
        head_sha=asked.head_sha,
        base_sha=asked.base_sha,
        agent_id=asked.agent_id,
        corpus_version=asked.corpus_version,
        correlation=asked.correlation,
    )


class WorkflowReviews:
    """The proxy for the reviews of checkout agents.

    If an activity fails for good, the use case is given
    ``ReviewIncompleteError``. It never sees an error of Temporal's.

    ``completed`` holds, for each agent, the run a completion signal
    named. ``told`` counts the completion signals for each agent. The
    workflow owns both and updates them when a signal arrives.
    """

    def __init__(
        self, completed: dict[str, str], told: dict[str, int] | None = None
    ) -> None:
        self._completed = completed
        self._told = told if told is not None else {}
        self._since: dict[str, datetime] = {}
        self._waits: dict[str, int] = {}

    async def agents(self) -> list[str]:
        agents: list[str] = await workflow.execute_activity(
            REVIEW_AGENTS_ACTIVITY,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return agents

    async def dispatch(self, asked: ReviewAsked) -> Dispatched:
        self._since[asked.agent_id] = workflow.now()
        try:
            dispatched: DispatchedReview = await workflow.execute_activity(
                REVIEW_DISPATCH_ACTIVITY,
                _asking(asked),
                result_type=DispatchedReview,
                start_to_close_timeout=timedelta(minutes=5),
                task_queue=judge_task_queue(workflow.info().task_queue),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except ActivityError as exc:
            raise ReviewIncompleteError(str(exc.cause or exc)) from exc
        return Dispatched(
            handle=dispatched.handle,
            reason=dispatched.reason,
            reused=dispatched.reused,
        )

    async def finished(self, agent_id: str, remote_id: str) -> bool:
        """The older way to wait: for a completion signal, with a timer of
        ``REVIEW_DEADLINE`` beside it. Returns False if the timer won.
        """
        try:
            await workflow.wait_condition(
                lambda: self._completed.get(agent_id) == remote_id,
                timeout=REVIEW_DEADLINE,
            )
        except TimeoutError:
            return False
        return True

    async def wait(self, asked: ReviewAsked, handle: Handle) -> bool:
        """Wait for the run to have something to read, for at most
        ``REVIEW_DEADLINE``.
        """
        return await self._waited(asked, handle, REVIEW_DEADLINE)

    async def _waited(
        self, asked: ReviewAsked, handle: Handle, patience: timedelta
    ) -> bool:
        """Run the wait activity once, for at most ``patience``.

        The activity is allowed a minute more than ``patience``. So the
        runner's adapter is what gives up, and the answer is "not ready"
        and not a failed activity.
        """
        turn = self._waits.get(asked.agent_id, 0) + 1
        self._waits[asked.agent_id] = turn
        named: str | None = (
            wait_id(asked.agent_id, handle.remote_id, turn)
            if workflow.patched(A_WAIT_HAS_A_NAME)
            else None
        )
        waited: WaitReviewResponse = await workflow.execute_activity(
            REVIEW_WAIT_ACTIVITY,
            WaitReviewRequest(
                ref=asked.ref,
                head_sha=asked.head_sha,
                agent_id=asked.agent_id,
                correlation=asked.correlation,
                handle=handle,
                patience=patience.total_seconds(),
            ),
            result_type=WaitReviewResponse,
            schedule_to_close_timeout=patience + timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=1),
            activity_id=named,
        )
        return bool(waited.ready)

    async def stop(self, handle: Handle) -> None:
        try:
            await workflow.execute_activity(
                REVIEW_STOP_ACTIVITY,
                handle,
                start_to_close_timeout=timedelta(minutes=2),
                task_queue=judge_task_queue(workflow.info().task_queue),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except ActivityError as exc:
            raise ReviewIncompleteError(str(exc.cause or exc)) from exc

    async def collect(self, asked: ReviewAsked, handle: Handle) -> Reviewed:
        """Read and grade the review. While the answer is that the run was
        asked for another answer, wait and read again, until the review's
        deadline. A run still going at the deadline is stopped.
        """
        agent = asked.agent_id
        before = self._told.get(agent, 0)
        collected = await self._collect(asked, handle)
        if collected.running and workflow.patched(ASK_AGAIN):
            deadline = self._since.get(agent, workflow.now()) + REVIEW_DEADLINE
            while collected.running:
                left = deadline - workflow.now()
                if left <= timedelta():
                    break
                if workflow.patched(THE_PORT_WAITS):
                    if not await self._waited(asked, handle, left):
                        break
                else:
                    try:
                        await workflow.wait_condition(
                            self._told_since(agent, before), timeout=left
                        )
                    except TimeoutError:
                        break
                before = self._told.get(agent, 0)
                collected = await self._collect(asked, handle)
            if collected.running:
                await self.stop(handle)
                return Reviewed(
                    reason="the review was asked for another answer and "
                    "did not give one by its deadline"
                )
        return Reviewed(
            verdict=collected.verdict,
            note=collected.note,
            reason=collected.reason,
        )

    def _told_since(self, agent: str, seen: int) -> Callable[[], bool]:
        """A test of whether this agent's run has signalled a completion
        since ``seen`` of them had arrived.
        """
        return lambda: self._told.get(agent, 0) > seen

    async def _collect(
        self, asked: ReviewAsked, handle: Handle
    ) -> ReviewAgentActivityResponse:
        """Run the collect activity once."""
        try:
            collected: ReviewAgentActivityResponse = (
                await workflow.execute_activity(
                    REVIEW_COLLECT_ACTIVITY,
                    ReviewCollectActivityRequest(
                        review=_asking(asked), handle=handle
                    ),
                    result_type=ReviewAgentActivityResponse,
                    start_to_close_timeout=timedelta(minutes=10),
                    task_queue=judge_task_queue(workflow.info().task_queue),
                    retry_policy=RetryPolicy(maximum_attempts=4),
                )
            )
        except ActivityError as exc:
            raise ReviewIncompleteError(str(exc.cause or exc)) from exc
        return collected


class WorkflowPublishing:
    """The proxy for publishing."""

    async def publish(self, publication: Publication) -> Published:
        published: PublishFindingsResponse = await workflow.execute_activity(
            PUBLISH_ACTIVITY,
            PublishFindingsRequest(
                ref=publication.ref,
                findings=publication.findings,
                judge_status=publication.judge_status,
                unavailable=publication.unavailable,
                answered=publication.answered,
                clauses=publication.clauses,
                corpus_version=publication.corpus_version,
                correlation=publication.correlation,
                head_sha=publication.head_sha,
                snapshot_id=publication.snapshot_id,
                verdicts=publication.verdicts,
                notes=publication.notes,
                publish=publication.publish,
            ),
            result_type=PublishFindingsResponse,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=patient(PUBLISH_MAX_ATTEMPTS),
        )
        return Published(status=published.status, resolved=published.resolved)


OBSERVE_ACTIVITY = "observe_pull_request"
OBSERVE_MAX_ATTEMPTS = 5


class WorkflowObservation:
    """The proxy for reading the pull request. It runs the forge
    context's activity and turns its answer into this context's types.
    """

    async def observe(
        self,
        ref: PullRequestRef,
        correlation: Correlation,
        delivery_ids: tuple[str, ...],
    ) -> Observation:
        observed: ObservePullRequestResponse = await workflow.execute_activity(
            OBSERVE_ACTIVITY,
            ObservePullRequestRequest(
                ref=ref, correlation=correlation, delivery_ids=delivery_ids
            ),
            result_type=ObservePullRequestResponse,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=patient(OBSERVE_MAX_ATTEMPTS),
        )
        summary = observed.summary
        return Observation(
            submission=SubmissionRef(
                snapshot_id=observed.snapshot.snapshot_id,
                ref=observed.snapshot.ref,
            ),
            title=summary.title,
            head_branch=summary.head_branch,
            base_branch=summary.base_branch,
            commit_count=summary.commit_count,
            file_count=summary.file_count,
            changed_lines=summary.changed_lines,
            head_sha=summary.head_sha,
            base_sha=summary.base_sha,
            corpus=Corpus(
                doctrine=DoctrineText(text=observed.corpus.doctrine_text),
                judge=observed.corpus.judge_fingerprint,
                installed=observed.corpus.installed,
                reporting_agent=observed.corpus.reporting_agent,
            ),
            judged_before=observed.judged_before,
        )


@workflow.defn(name=EVALUATE_WORKFLOW)
class EvaluatePullRequestWorkflow:
    """The workflow. It builds the use case with the five proxies and
    runs it.
    """

    def __init__(self) -> None:
        self._completed: dict[str, str] = {}
        self._told: dict[str, int] = {}

    @workflow.signal(name=REVIEW_COMPLETE_SIGNAL)
    def review_complete(self, agent_id: str, remote_id: str) -> None:
        """Note that a runner has finished a run for an agent."""
        self._completed[agent_id] = remote_id
        self._told[agent_id] = self._told.get(agent_id, 0) + 1

    @workflow.run
    async def run(
        self, request: EvaluatePullRequestRequest
    ) -> EvaluatePullRequestResponse:
        return await EvaluatePullRequestUseCase(
            execution=WorkflowExecution(),
            observation=WorkflowObservation(),
            assessment=WorkflowAssessment(),
            reviews=WorkflowReviews(self._completed, self._told),
            publishing=WorkflowPublishing(),
        ).execute(request)
