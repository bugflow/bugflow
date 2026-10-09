"""Tests of ``EvaluatePullRequestUseCase``: the order of an
evaluation's steps, what is skipped, and what a failed review
becomes."""

import asyncio
from dataclasses import replace

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
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.review import ReviewVerdict
from bugflow.review.domain.models.submission import SubmissionRef
from bugflow.review.dtos.evaluate_pull_request import (
    EvaluatePullRequestRequest,
    EvaluatePullRequestResponse,
)
from bugflow.review.usecases.evaluate_pull_request import (
    EvaluatePullRequestUseCase,
)
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="orchard", repo="pear-tree", number=7)
CORRELATION = Correlation(workflow_id="in-process", run_id="1")
CORPUS = Corpus(
    doctrine=DoctrineText(text="**RULE-104.** A commit does one thing."),
    judge=None,
)
CHECKED = Finding(
    policy_id="P-04",
    severity="warn",
    clause="RULE-21",
    subject="description",
    message="an em dash",
)
JUDGED = Finding(
    policy_id="Q-01",
    severity="warn",
    clause="RULE-104",
    subject="pull request",
    message="two things",
    judged_by="fake-model",
)
OBSERVED = Observation(
    submission=SubmissionRef(snapshot_id="a" * 64, ref=REF),
    title="Add the judge port",
    head_branch="judge-port",
    base_branch="master",
    commit_count=1,
    file_count=0,
    changed_lines=0,
    head_sha="b" * 40,
    base_sha="",
    corpus=CORPUS,
)


class Here:
    def __init__(self) -> None:
        self.settled_changes: list[str] = []

    def correlation(self) -> Correlation:
        return CORRELATION

    def changed(self, change_id: str) -> bool:
        return True

    def settled(self, change_id: str) -> None:
        self.settled_changes.append(change_id)


class Observing:
    def __init__(self, observed: Observation = OBSERVED) -> None:
        self._observed = observed
        self.deliveries: list[tuple[str, ...]] = []

    async def observe(
        self,
        ref: PullRequestRef,
        correlation: Correlation,
        delivery_ids: tuple[str, ...],
    ) -> Observation:
        self.deliveries.append(delivery_ids)
        return self._observed


class Checking:
    def __init__(self) -> None:
        self.stamped: list[tuple[str, str]] = []

    async def check(
        self,
        submission: SubmissionRef,
        corpus_version: str,
        agent_id: str,
        correlation: Correlation,
    ) -> Assessed:
        self.stamped.append((agent_id, corpus_version))
        return Assessed(
            findings=(CHECKED,), status="checked", answered=("P-04",)
        )


class Judging:
    def __init__(
        self,
        policies: tuple[str, ...] = ("P-01", "Q-01"),
        unavailable: frozenset[str] = frozenset(),
    ) -> None:
        self._policies = policies
        self._unavailable = unavailable
        self.asked: list[str | None] = []
        self.at_commit: list[str | None] = []

    async def policies(self, forge: str, repo: str) -> list[str]:
        return list(self._policies)

    async def judge(
        self,
        submission: SubmissionRef,
        corpus: Corpus,
        correlation: Correlation,
        use_judge: bool,
        policy_id: str | None,
        head_sha: str | None = None,
    ) -> Assessed:
        self.asked.append(policy_id)
        self.at_commit.append(head_sha)
        if policy_id in self._unavailable:
            return Assessed(
                findings=(),
                status=f"unavailable: {policy_id}",
                unavailable=(policy_id,),
            )
        return Assessed(
            findings=(replace(JUDGED, policy_id=policy_id or "every"),),
            status=f"{policy_id} judged",
            answered=(policy_id,) if policy_id else (),
        )


class Assessing:
    def __init__(
        self,
        policies: tuple[Answerable, ...] = (
            Answerable(policy_id="P-01", model_class="medium"),
            Answerable(policy_id="P-04"),
            Answerable(policy_id="Q-01", model_class="medium"),
        ),
        unavailable: frozenset[str] = frozenset(),
    ) -> None:
        self._policies = policies
        self._unavailable = unavailable
        self.asked: list[str] = []
        self.at_commit: list[str | None] = []
        self.unjudged_asked = 0

    async def policies(self, forge: str, repo: str) -> list[Answerable]:
        return list(self._policies)

    async def assess(
        self,
        policy: Answerable,
        submission: SubmissionRef,
        corpus: Corpus,
        correlation: Correlation,
        head_sha: str | None = None,
    ) -> Assessed:
        self.asked.append(policy.policy_id)
        self.at_commit.append(head_sha)
        if policy.policy_id in self._unavailable:
            return Assessed(
                findings=(),
                status=f"unavailable: {policy.policy_id}",
                unavailable=(policy.policy_id,),
            )
        return Assessed(
            findings=(replace(JUDGED, policy_id=policy.policy_id),),
            status=f"{policy.policy_id} answered",
            answered=(policy.policy_id,),
        )

    async def unjudged(
        self,
        submission: SubmissionRef,
        corpus: Corpus,
        correlation: Correlation,
        head_sha: str | None = None,
    ) -> Assessed:
        self.unjudged_asked += 1
        return Assessed(findings=(), status="no judge asked")


class Reviewing:
    def __init__(
        self,
        agents: tuple[str, ...] = ("safety", "licence"),
        late: frozenset[str] = frozenset(),
        unreadable: frozenset[str] = frozenset(),
        declined: frozenset[str] = frozenset(),
        reviewed: frozenset[str] = frozenset(),
    ) -> None:
        self._agents, self._late = agents, late
        self._unreadable, self._declined = unreadable, declined
        self._reviewed = reviewed
        self.dispatched: list[str] = []
        self.stopped: list[str] = []
        self.collected: list[str] = []
        self.stamped: list[tuple[str, str]] = []

    async def agents(self) -> list[str]:
        return list(self._agents)

    async def dispatch(self, asked: ReviewAsked) -> Dispatched:
        self.dispatched.append(asked.agent_id)
        self.stamped.append((asked.agent_id, asked.corpus_version))
        if asked.agent_id in self._declined:
            return Dispatched(reason="no runner is configured")
        if asked.agent_id in self._reviewed:
            return Dispatched(
                reason="reviewed already at this commit, by this version",
                reused=ReviewVerdict(
                    agent_id=asked.agent_id,
                    head_sha=asked.head_sha,
                    status="warn",
                ),
            )
        return Dispatched(
            handle=Handle(
                runner="double", fingerprint="f", remote_id=asked.agent_id
            )
        )

    async def finished(self, agent_id: str, remote_id: str) -> bool:
        raise AssertionError("the port waits now")

    async def wait(self, asked: ReviewAsked, handle: Handle) -> bool:
        return asked.agent_id not in self._late

    async def stop(self, handle: Handle) -> None:
        self.stopped.append(handle.remote_id)

    async def collect(self, asked: ReviewAsked, handle: Handle) -> Reviewed:
        self.collected.append(asked.agent_id)
        if asked.agent_id in self._unreadable:
            raise ReviewIncompleteError("the grader answered 429")
        return Reviewed(
            verdict=ReviewVerdict(
                agent_id=asked.agent_id, head_sha=asked.head_sha, status="pass"
            )
        )


class Publishing:
    def __init__(self) -> None:
        self.published: list[Publication] = []

    async def publish(self, publication: Publication) -> Published:
        self.published.append(publication)
        return Published(status="published")


def evaluate(
    observing: Observing | None = None,
    assessing: Assessing | None = None,
    reviewing: Reviewing | None = None,
    request: EvaluatePullRequestRequest | None = None,
) -> tuple[EvaluatePullRequestResponse, Publication]:
    publishing = Publishing()
    response = asyncio.run(
        EvaluatePullRequestUseCase(
            Here(),
            observing or Observing(),
            assessing or Assessing(),
            reviewing or Reviewing(),
            publishing,
        ).execute(request or EvaluatePullRequestRequest(ref=REF))
    )
    return response, publishing.published[-1]


def test_each_policy_is_asked_for_on_its_own_and_all_are_published() -> None:
    assessing = Assessing()

    response, publication = evaluate(assessing=assessing)

    assert assessing.asked == ["P-01", "P-04", "Q-01"]
    assert [f.policy_id for f in publication.findings] == [
        "P-01",
        "P-04",
        "Q-01",
    ]
    assert response.findings == publication.findings
    assert response.judge_status == (
        "P-01 answered; P-04 answered; Q-01 answered"
    )
    assert response.publish_status == "published"
    assert (response.workflow_id, response.run_id) == ("in-process", "1")


def test_a_repository_reviewed_for_nothing_is_judged_on_nothing() -> None:
    assessing = Assessing(policies=())

    response, _ = evaluate(assessing=assessing)

    assert assessing.asked == []
    assert "reviewed for no policy" in response.judge_status


def test_every_answer_is_told_which_commit_it_is_about() -> None:
    assessing = Assessing()

    evaluate(assessing=assessing)

    assert assessing.at_commit == ["b" * 40] * 3


def test_without_the_judge_no_policy_is_asked_for() -> None:
    assessing = Assessing()

    evaluate(
        assessing=assessing,
        request=EvaluatePullRequestRequest(ref=REF, use_judge=False),
    )

    assert assessing.asked == []
    assert assessing.unjudged_asked == 1


def test_a_commit_judged_before_is_not_judged_again() -> None:
    assessing = Assessing()

    response, publication = evaluate(
        observing=Observing(replace(OBSERVED, judged_before=True)),
        assessing=assessing,
    )

    assert assessing.asked == []
    assert publication.findings == ()
    assert "already judged" in response.judge_status
    assert publication.answered == ()


def test_the_doctrines_words_for_each_cited_clause_reach_publishing() -> None:
    _, publication = evaluate()

    assert publication.clauses == {
        "RULE-104": "**RULE-104.** A commit does one thing."
    }


def test_the_deliveries_answered_and_whether_to_publish_are_passed_on() -> (
    None
):
    observing = Observing()

    _, publication = evaluate(
        observing=observing,
        request=EvaluatePullRequestRequest(
            ref=REF, delivery_ids=("d1", "d2"), publish=False
        ),
    )

    assert observing.deliveries == [("d1", "d2")]
    assert publication.publish is False


def test_every_installed_agent_reviews_the_head_commit() -> None:
    _, publication = evaluate()

    assert [(v.agent_id, v.head_sha) for v in publication.verdicts] == [
        ("safety", "b" * 40),
        ("licence", "b" * 40),
    ]


def test_nothing_is_dispatched_without_a_head_commit() -> None:
    reviewing = Reviewing()

    _, publication = evaluate(
        observing=Observing(replace(OBSERVED, head_sha=None)),
        reviewing=reviewing,
    )

    assert reviewing.dispatched == []
    assert publication.verdicts == ()


def test_a_review_past_its_deadline_is_stopped_then_read() -> None:
    reviewing = Reviewing(late=frozenset({"safety"}))

    _, publication = evaluate(reviewing=reviewing)

    assert reviewing.stopped == ["safety"]
    assert len(publication.verdicts) == 2


def test_an_unreadable_review_costs_its_own_verdict_and_no_other() -> None:
    _, publication = evaluate(
        reviewing=Reviewing(unreadable=frozenset({"safety"}))
    )

    assert [v.agent_id for v in publication.verdicts] == ["licence"]


def test_an_agent_nothing_would_run_has_no_verdict() -> None:
    reviewing = Reviewing(declined=frozenset({"safety"}))

    _, publication = evaluate(reviewing=reviewing)

    assert reviewing.stopped == []
    assert [v.agent_id for v in publication.verdicts] == ["licence"]


def test_a_verdict_reused_for_this_commit_is_published_without_a_run() -> None:
    reviewing = Reviewing(reviewed=frozenset({"safety"}))

    _, publication = evaluate(reviewing=reviewing)

    assert reviewing.collected == ["licence"]
    assert sorted((v.agent_id, v.status) for v in publication.verdicts) == [
        ("licence", "pass"),
        ("safety", "warn"),
    ]


INSTALLED = Corpus(
    doctrine=CORPUS.doctrine,
    judge=None,
    installed={
        "prose": "prose-v1",
        "safety": "safety-v1",
        "licence": "licence-v1",
    },
    reporting_agent="prose",
)


def test_each_review_is_given_the_version_of_the_agent_it_is_for() -> None:
    reviewing = Reviewing()

    evaluate(
        observing=Observing(replace(OBSERVED, corpus=INSTALLED)),
        reviewing=reviewing,
    )

    assert reviewing.stamped == [
        ("safety", "safety-v1"),
        ("licence", "licence-v1"),
    ]


def test_a_policy_nothing_could_answer_is_named_to_publishing() -> None:
    _, publication = evaluate(
        assessing=Assessing(unavailable=frozenset({"Q-01"}))
    )
    assert publication.unavailable == ("Q-01",)
    assert publication.answered == ("P-01", "P-04")


def test_publishing_is_told_which_policies_ran() -> None:
    _, publication = evaluate()
    assert publication.answered == ("P-01", "P-04", "Q-01")
