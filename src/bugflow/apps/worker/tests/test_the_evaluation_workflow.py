"""Tests of the evaluation workflow, run by Temporal's test server.

Stand-ins take the place of the real activities. So these test the
workflow's steps: their order, what is passed between them, and that
each is given the workflow run it belongs to.

The last four tests replay recorded histories. See the docstring of the
first of them.
"""

import asyncio
import os
import re
import uuid
from dataclasses import replace
from pathlib import Path

from temporalio import activity
from temporalio.client import Client, WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from bugflow.apps.worker.evaluate_pull_request import (
    ASSESS_ACTIVITY,
    CHECK_ACTIVITY,
    JUDGE_ACTIVITY,
    OBSERVE_ACTIVITY,
    POLICIES_ACTIVITY,
    PUBLISH_ACTIVITY,
    REVIEW_AGENTS_ACTIVITY,
    REVIEW_COLLECT_ACTIVITY,
    REVIEW_COMPLETE_SIGNAL,
    REVIEW_DISPATCH_ACTIVITY,
    REVIEW_STOP_ACTIVITY,
    REVIEW_WAIT_ACTIVITY,
    EvaluatePullRequestWorkflow,
    judge_task_queue,
    workflow_id_for,
)
from bugflow.apps.worker.worker import workflow_runner
from bugflow.forge.domain.models.pull_request import (
    CommitSnapshot,
    PullRequestSnapshot,
    SnapshotRef,
)
from bugflow.forge.domain.values.evaluation_regime import EvaluationRegime
from bugflow.forge.dtos.observe_pull_request import (
    ObservePullRequestRequest,
    ObservePullRequestResponse,
)
from bugflow.review.domain.models.corpus import Corpus
from bugflow.review.domain.models.delegation import Handle
from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.evaluation import Answerable
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.review import ReviewNote, ReviewVerdict
from bugflow.review.domain.models.submission import SubmissionRef
from bugflow.review.dtos.assess_policy import (
    AssessPolicyRequest,
    AssessPolicyResponse,
)
from bugflow.review.dtos.check_pull_request import (
    CheckPullRequestRequest,
    CheckPullRequestResponse,
)
from bugflow.review.dtos.evaluate_pull_request import (
    EvaluatePullRequestRequest,
    EvaluatePullRequestResponse,
)
from bugflow.review.dtos.judge_pull_request import (
    JudgePullRequestRequest,
    JudgePullRequestResponse,
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
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="orchard", repo="pear-tree", number=7)
DOCTRINE = DoctrineText(text="RULE-4. A commit does one thing.")
CORPUS = Corpus(doctrine=DOCTRINE, judge=None)
REVIEW_CORPUS = CORPUS
REGIME = EvaluationRegime(
    doctrine_text=CORPUS.doctrine.text,
    judge_fingerprint=CORPUS.judge,
    version=CORPUS.version,
    components=CORPUS.components(),
)
SNAPSHOT = PullRequestSnapshot(
    ref=REF,
    title="Add the judge port",
    body="Introduce the judge port.",
    head_branch="judge-port",
    base_branch="master",
    commits=(CommitSnapshot(sha="a" * 40, message="Add the port\n"),),
    files=(),
)
REFERENCE = SnapshotRef(snapshot_id=SNAPSHOT.content_id, ref=REF)
SUBMISSION_REFERENCE = SubmissionRef(
    snapshot_id=REFERENCE.snapshot_id, ref=REFERENCE.ref
)
JUDGED = Finding(
    policy_id="Q-01",
    severity="warn",
    clause="RULE-4",
    subject="pull request",
    message="two things",
    judged_by="fake-model",
)
CHECKED = Finding(
    policy_id="P-04",
    severity="warn",
    clause="RULE-21",
    subject='description "a dash"',
    message='"a dash": an em dash stands here where a full stop belongs.',
)

correlations: list[Correlation] = []
observed_deliveries: list[tuple[str, ...]] = []
judge_requests: list[JudgePullRequestRequest] = []
publish_requests: list[PublishFindingsRequest] = []


@activity.defn(name=OBSERVE_ACTIVITY)
async def fake_observe(
    request: ObservePullRequestRequest,
) -> ObservePullRequestResponse:
    correlations.append(request.correlation)
    observed_deliveries.append(request.delivery_ids)
    return ObservePullRequestResponse(
        snapshot=REFERENCE, summary=SNAPSHOT.summary(), corpus=REGIME
    )


POLICIES = (
    Answerable(policy_id="P-01", model_class="medium"),
    Answerable(policy_id="Q-01", model_class="medium"),
    Answerable(policy_id="P-04"),
)
policies_asked: list[int] = []
AGENTS: tuple[str, ...] = ()


@activity.defn(name=POLICIES_ACTIVITY)
async def fake_review_policies(forge: str, repo: str) -> list[Answerable]:
    policies_asked.append(1)
    return list(POLICIES)


assess_queues: list[str] = []


@activity.defn(name=ASSESS_ACTIVITY)
async def fake_assess(request: AssessPolicyRequest) -> AssessPolicyResponse:
    """Answers a policy, and records which task queue it ran on."""
    correlations.append(request.correlation)
    assess_requests.append(request)
    assess_queues.append(activity.info().task_queue)
    policy = request.policy_id or "every policy"
    if policy == "P-04":
        return AssessPolicyResponse(
            findings=(CHECKED,),
            status="checked: 1 em dashes",
            answered=("P-04",),
        )
    return AssessPolicyResponse(
        findings=(replace(JUDGED, policy_id=policy),),
        status=f"{policy} judged by fake-model",
        answered=(policy,) if request.policy_id else (),
    )


assess_requests: list[AssessPolicyRequest] = []


reviews_asked: list[str] = []
stopped: list[str] = []
collected: list[str] = []
UNREADABLE: set[str] = set()
UNSIGNALLED: set[str] = set()
ASKED_AGAIN: set[str] = set()
ANSWER_AGAIN: set[str] = set()
CLIENT: Client | None = None


@activity.defn(name=REVIEW_AGENTS_ACTIVITY)
async def fake_review_agents() -> list[str]:
    return list(AGENTS)


@activity.defn(name=REVIEW_DISPATCH_ACTIVITY)
async def fake_dispatch(
    request: ReviewAgentActivityRequest,
) -> DispatchedReview:
    reviews_asked.append(request.agent_id)
    remote_id = f"session_{request.agent_id}"
    if request.agent_id not in UNSIGNALLED:
        assert CLIENT is not None
        await CLIENT.get_workflow_handle(
            request.correlation.workflow_id,
            run_id=request.correlation.run_id,
        ).signal(REVIEW_COMPLETE_SIGNAL, args=[request.agent_id, remote_id])
    return DispatchedReview(
        handle=Handle(runner="fake", fingerprint="abc123", remote_id=remote_id)
    )


waits: list[str] = []


@activity.defn(name=REVIEW_WAIT_ACTIVITY)
async def fake_wait(request: WaitReviewRequest) -> WaitReviewResponse:
    """Says whether a run has something to read. "Not ready" stands for
    the time running out.
    """
    agent = request.agent_id
    waits.append(agent)
    if agent in UNSIGNALLED:
        return WaitReviewResponse(ready=False)
    if waits.count(agent) > 1 and agent not in ANSWER_AGAIN:
        return WaitReviewResponse(ready=False)
    return WaitReviewResponse(ready=True)


@activity.defn(name=REVIEW_STOP_ACTIVITY)
async def fake_stop(handle: Handle) -> None:
    stopped.append(handle.remote_id)


@activity.defn(name=REVIEW_COLLECT_ACTIVITY)
async def fake_collect(
    request: ReviewCollectActivityRequest,
) -> ReviewAgentActivityResponse:
    collected.append(request.handle.remote_id)
    if request.review.agent_id in UNREADABLE:
        raise ApplicationError("the grader answered 429", non_retryable=True)
    agent_id = request.review.agent_id
    if (
        agent_id in ASKED_AGAIN
        and collected.count(request.handle.remote_id) == 1
    ):
        if agent_id in ANSWER_AGAIN:
            assert CLIENT is not None
            await CLIENT.get_workflow_handle(
                request.review.correlation.workflow_id,
                run_id=request.review.correlation.run_id,
            ).signal(
                REVIEW_COMPLETE_SIGNAL,
                args=[agent_id, request.handle.remote_id],
            )
        return ReviewAgentActivityResponse(
            reason="the run has not finished", running=True
        )
    return ReviewAgentActivityResponse(
        verdict=ReviewVerdict(
            agent_id=request.review.agent_id,
            head_sha=request.review.head_sha,
            status="pass",
        ),
        note=ReviewNote(
            agent_id=request.review.agent_id,
            head_sha=request.review.head_sha,
            note="It holds.",
        ),
    )


@activity.defn(name=JUDGE_ACTIVITY)
async def fake_judge(
    request: JudgePullRequestRequest,
) -> JudgePullRequestResponse:
    correlations.append(request.correlation)
    judge_requests.append(request)
    policy = request.policy_id or "every policy"
    return JudgePullRequestResponse(
        findings=(replace(JUDGED, policy_id=policy),),
        status=f"{policy} judged by fake-model",
    )


check_requests: list[CheckPullRequestRequest] = []


@activity.defn(name=CHECK_ACTIVITY)
async def fake_check(
    request: CheckPullRequestRequest,
) -> CheckPullRequestResponse:
    correlations.append(request.correlation)
    check_requests.append(request)
    return CheckPullRequestResponse(
        findings=(CHECKED,), status="checked: 1 em dashes"
    )


@activity.defn(name=PUBLISH_ACTIVITY)
async def fake_publish(
    request: PublishFindingsRequest,
) -> PublishFindingsResponse:
    correlations.append(request.correlation)
    publish_requests.append(request)
    return PublishFindingsResponse(
        status="skipped: publishing disabled",
        label="review:escalate",
        comment="summary",
    )


async def evaluate(
    use_judge: bool,
    delivery_ids: tuple[str, ...] = (),
    publish: bool = True,
    histories: list[WorkflowHistory] | None = None,
) -> EvaluatePullRequestResponse:
    """Run one evaluation on the test server and return its response.
    If ``histories`` is given, the run's history is added to it.
    """
    global CLIENT
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        CLIENT = env.client
        task_queue = f"test-{uuid.uuid4()}"
        async with (
            Worker(
                env.client,
                task_queue=task_queue,
                workflows=[EvaluatePullRequestWorkflow],
                activities=[
                    fake_observe,
                    fake_review_policies,
                    fake_assess,
                    fake_review_agents,
                    fake_wait,
                    fake_check,
                    fake_publish,
                ],
                workflow_runner=workflow_runner(),
            ),
            Worker(
                env.client,
                task_queue=judge_task_queue(task_queue),
                activities=[
                    fake_judge,
                    fake_assess,
                    fake_dispatch,
                    fake_stop,
                    fake_collect,
                ],
            ),
            Worker(
                env.client,
                task_queue=f"{judge_task_queue(task_queue)}-medium",
                activities=[fake_assess],
            ),
        ):
            handle = await env.client.start_workflow(
                EvaluatePullRequestWorkflow.run,
                EvaluatePullRequestRequest(
                    ref=REF,
                    use_judge=use_judge,
                    delivery_ids=delivery_ids,
                    publish=publish,
                ),
                id=workflow_id_for(REF),
                task_queue=task_queue,
            )
            response = await handle.result()
            if histories is not None:
                histories.append(await handle.fetch_history())
            return response


def test_each_policy_is_answered_by_an_activity_of_its_own() -> None:
    correlations.clear()
    assess_requests.clear()
    policies_asked.clear()
    response = asyncio.run(evaluate(use_judge=True))

    assert len(policies_asked) == 1
    assert {r.policy_id for r in assess_requests} == {
        one.policy_id for one in POLICIES
    }
    assert len(assess_requests) == len(POLICIES)
    assert [f.policy_id for f in response.findings] == [
        one.policy_id for one in POLICIES
    ]
    assert response.judge_status == (
        "P-01 judged by fake-model; Q-01 judged by fake-model; "
        "checked: 1 em dashes"
    )
    assert response.corpus_version == CORPUS.version
    assert assess_requests[0].corpus == REVIEW_CORPUS
    assert assess_requests[0].use_judge is True


def test_each_class_of_model_has_a_queue_of_its_own() -> None:
    assess_requests.clear()
    assess_queues.clear()
    asyncio.run(evaluate(use_judge=True))

    where = dict(
        zip([r.policy_id for r in assess_requests], assess_queues, strict=True)
    )
    assert where["P-01"].endswith("-judge-medium")
    assert where["Q-01"].endswith("-judge-medium")
    assert "judge" not in where["P-04"]


def test_every_step_receives_the_correlation_of_the_running_execution() -> (
    None
):
    correlations.clear()
    assess_requests.clear()
    response = asyncio.run(evaluate(use_judge=False))

    assert response.workflow_id == "pr/github/orchard/pear-tree/7"
    assert len(correlations) == 3
    assert set(correlations) == {
        Correlation(workflow_id=response.workflow_id, run_id=response.run_id)
    }
    assert assess_requests[0].use_judge is False


def test_the_deliveries_the_evaluation_answers_reach_observation() -> None:
    observed_deliveries.clear()
    asyncio.run(evaluate(use_judge=False, delivery_ids=("d-1", "d-2")))
    assert observed_deliveries == [("d-1", "d-2")]


def test_later_steps_receive_the_stored_snapshot_by_reference() -> None:
    assess_requests.clear()
    response = asyncio.run(evaluate(use_judge=True))

    assert assess_requests[0].snapshot == SUBMISSION_REFERENCE
    assert (response.title, response.commit_count) == (SNAPSHOT.title, 1)


def test_every_finding_is_handed_to_publishing() -> None:
    publish_requests.clear()
    response = asyncio.run(evaluate(use_judge=True))

    (request,) = publish_requests
    assert [f.policy_id for f in request.findings] == [
        one.policy_id for one in POLICIES
    ]
    assert request.corpus_version == CORPUS.version
    assert request.judge_status == (
        "P-01 judged by fake-model; Q-01 judged by fake-model; "
        "checked: 1 em dashes"
    )
    assert response.publish_status == "skipped: publishing disabled"


def test_publishing_receives_the_head_commit_and_whether_to_publish() -> None:
    publish_requests.clear()
    asyncio.run(evaluate(use_judge=False, publish=False))
    (request,) = publish_requests
    assert request.publish is False
    assert request.head_sha == "a" * 40


def test_no_agent_installed_dispatches_nothing() -> None:
    reviews_asked.clear()
    publish_requests.clear()
    asyncio.run(evaluate(use_judge=False))
    assert reviews_asked == []
    assert publish_requests[-1].verdicts == ()


def test_every_installed_agent_is_dispatched_and_its_verdict_published() -> (
    None
):
    global AGENTS
    reviews_asked.clear()
    publish_requests.clear()
    AGENTS = ("safety", "design")
    try:
        asyncio.run(evaluate(use_judge=False))
    finally:
        AGENTS = ()
    assert sorted(reviews_asked) == ["design", "safety"]
    reported = publish_requests[-1].verdicts
    assert sorted(v.agent_id for v in reported) == ["design", "safety"]
    assert {v.status for v in reported} == {"pass"}
    notes = publish_requests[-1].notes
    assert sorted(n.agent_id for n in notes) == ["design", "safety"]


def test_a_review_is_dispatched_waited_on_then_collected() -> None:
    global AGENTS
    for record in (reviews_asked, stopped, collected, waits):
        record.clear()
    AGENTS = ("safety",)
    try:
        asyncio.run(evaluate(use_judge=False))
    finally:
        AGENTS = ()
    assert reviews_asked == ["safety"]
    assert waits == ["safety"], "waited on once, through the port"
    assert collected == ["session_safety"]
    assert stopped == [], "a run that answered is not stopped"


def test_a_review_asked_again_is_collected_at_its_next_completion() -> None:
    global AGENTS
    for record in (reviews_asked, stopped, collected, waits):
        record.clear()
    AGENTS = ("safety",)
    ASKED_AGAIN.add("safety")
    ANSWER_AGAIN.add("safety")
    try:
        asyncio.run(evaluate(use_judge=False))
    finally:
        AGENTS = ()
        ASKED_AGAIN.clear()
        ANSWER_AGAIN.clear()
    assert collected == ["session_safety", "session_safety"]
    assert stopped == []


def test_a_review_asked_again_that_never_answers_is_stopped() -> None:
    global AGENTS
    for record in (reviews_asked, stopped, collected, waits):
        record.clear()
    AGENTS = ("safety",)
    ASKED_AGAIN.add("safety")
    try:
        asyncio.run(evaluate(use_judge=False))
    finally:
        AGENTS = ()
        ASKED_AGAIN.clear()
    assert collected == ["session_safety"]
    assert stopped == ["session_safety"]


def test_a_review_past_its_deadline_is_stopped_before_it_is_read() -> None:
    global AGENTS
    for record in (reviews_asked, stopped, collected, waits):
        record.clear()
    AGENTS = ("safety",)
    UNSIGNALLED.add("safety")
    try:
        asyncio.run(evaluate(use_judge=False))
    finally:
        AGENTS = ()
        UNSIGNALLED.clear()
    assert reviews_asked == ["safety"]
    assert stopped == ["session_safety"]
    assert collected == ["session_safety"]


def test_a_review_that_cannot_be_read_does_not_fail_the_evaluation() -> None:
    global AGENTS
    publish_requests.clear()
    AGENTS = ("safety", "design")
    UNREADABLE.add("safety")
    try:
        asyncio.run(evaluate(use_judge=False))
    finally:
        AGENTS = ()
        UNREADABLE.clear()
    reported = publish_requests[-1].verdicts
    assert [v.agent_id for v in reported] == ["design"]


HISTORY = Path(__file__).parent / "histories" / "evaluate_pull_request.json"


def test_a_history_recorded_by_earlier_code_still_replays() -> None:
    """Replay a history recorded from a run of this workflow.

    Temporal continues a running workflow by running its code again
    over the run's recorded history. If the code now asks for different
    steps, or a request or response has a field renamed or retyped,
    that fails for every run that is going when the worker restarts.
    This test fails first.

    A change that is meant to alter the steps records the history
    again, by running the tests with UPDATE_HISTORIES=1.
    """
    if os.environ.get("UPDATE_HISTORIES"):
        histories: list[WorkflowHistory] = []
        asyncio.run(evaluate(use_judge=True, histories=histories))
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(anonymous(histories[0].to_json()))
    recorded = WorkflowHistory.from_json(
        workflow_id_for(REF), HISTORY.read_text()
    )
    asyncio.run(
        Replayer(
            workflows=[EvaluatePullRequestWorkflow],
            data_converter=pydantic_data_converter,
            workflow_runner=workflow_runner(),
        ).replay_workflow(recorded)
    )


HISTORY_WITH_REVIEWER = HISTORY.with_name(
    "evaluate_pull_request_with_reviewer.json"
)


def test_a_reviewer_history_recorded_by_earlier_code_still_replays() -> None:
    """The same for an evaluation with one checkout agent, which is
    dispatched, waited for and collected.
    """
    global AGENTS
    if os.environ.get("UPDATE_HISTORIES"):
        histories: list[WorkflowHistory] = []
        AGENTS = ("safety",)
        try:
            asyncio.run(evaluate(use_judge=True, histories=histories))
        finally:
            AGENTS = ()
        HISTORY_WITH_REVIEWER.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_WITH_REVIEWER.write_text(anonymous(histories[0].to_json()))
    recorded = WorkflowHistory.from_json(
        workflow_id_for(REF), HISTORY_WITH_REVIEWER.read_text()
    )
    asyncio.run(
        Replayer(
            workflows=[EvaluatePullRequestWorkflow],
            data_converter=pydantic_data_converter,
            workflow_runner=workflow_runner(),
        ).replay_workflow(recorded)
    )


HISTORY_PAST_DEADLINE = HISTORY.with_name(
    "evaluate_pull_request_past_deadline.json"
)
HISTORY_UNREADABLE = HISTORY.with_name(
    "evaluate_pull_request_unreadable_review.json"
)


def test_a_deadline_history_recorded_by_earlier_code_still_replays() -> None:
    """The same for an evaluation whose checkout agent never becomes
    ready, so that the run is stopped.
    """
    global AGENTS
    if os.environ.get("UPDATE_HISTORIES"):
        histories: list[WorkflowHistory] = []
        AGENTS = ("safety",)
        UNSIGNALLED.add("safety")
        try:
            asyncio.run(evaluate(use_judge=True, histories=histories))
        finally:
            AGENTS = ()
            UNSIGNALLED.clear()
        HISTORY_PAST_DEADLINE.write_text(anonymous(histories[0].to_json()))
    replay(HISTORY_PAST_DEADLINE)


def test_an_unreadable_history_recorded_by_earlier_code_still_replays() -> (
    None
):
    """The same for an evaluation with two checkout agents, one of
    whose reviews cannot be read, and with no judging.
    """
    global AGENTS
    if os.environ.get("UPDATE_HISTORIES"):
        histories: list[WorkflowHistory] = []
        AGENTS = ("safety", "design")
        UNREADABLE.add("safety")
        try:
            asyncio.run(evaluate(use_judge=False, histories=histories))
        finally:
            AGENTS = ()
            UNREADABLE.clear()
        HISTORY_UNREADABLE.write_text(anonymous(histories[0].to_json()))
    replay(HISTORY_UNREADABLE)


def replay(history: Path) -> None:
    recorded = WorkflowHistory.from_json(
        workflow_id_for(REF), history.read_text()
    )
    asyncio.run(
        Replayer(
            workflows=[EvaluatePullRequestWorkflow],
            data_converter=pydantic_data_converter,
            workflow_runner=workflow_runner(),
        ).replay_workflow(recorded)
    )


def anonymous(history: str) -> str:
    """Remove the recording machine's name and the paths in stack traces
    from a history before it is saved. Neither matters for a replay.
    """
    history = re.sub(
        r'"stackTrace": "(?:[^"\\]|\\.)*"', '"stackTrace": ""', history
    )
    return re.sub(r'"identity": "[^"]*"', '"identity": "recorded"', history)
