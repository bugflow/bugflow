"""Tests of what the review activities let Temporal retry.

Run under Temporal's activity test environment, which supplies the
attempt number an activity reads to know whether it has attempts left.
"""

from datetime import timedelta

import pytest
from temporalio.exceptions import ApplicationError

from bugflow.apps.worker.activities import ReviewActivities
from bugflow.apps.worker.evaluate_pull_request import JUDGE_MAX_ATTEMPTS
from bugflow.apps.worker.tests.activities import (
    DOCTRINE,
    REF,
    RUN,
    SNAPSHOT,
    FailingForge,
    FakeDoctrine,
    FixedClock,
    at_attempt,
    gating,
)
from bugflow.forge.domain.errors import (
    ForgeRejectedError,
    ForgeUnavailableError,
)
from bugflow.forge.dtos.observe_pull_request import ObservePullRequestRequest
from bugflow.forge.infrastructure.in_memory_snapshots import (
    InMemorySnapshotStore,
)
from bugflow.review.domain.errors import JudgeTemporarilyUnavailableError
from bugflow.review.domain.facts import JUDGE_INVOKED
from bugflow.review.domain.models.corpus import Corpus
from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.judge_assessment import JudgeAssessment
from bugflow.review.domain.models.submission import Submission, SubmissionRef
from bugflow.review.dtos.judge_pull_request import JudgePullRequestRequest
from bugflow.review.dtos.publish_findings import PublishFindingsRequest
from bugflow.review.infrastructure.in_memory_judge_archive import (
    InMemoryJudgeArchive,
)
from bugflow.review.tests.journal import QueryableJournal

JUDGE_WAIT = timedelta(seconds=40)


class RateLimitedJudge:
    model_id = "a-model"
    fingerprint = "a-fingerprint"
    policies = ("P-01",)

    def assess(
        self,
        submission: Submission,
        doctrine: DoctrineText,
        policy_id: str = "P-01",
    ) -> JudgeAssessment:
        raise JudgeTemporarilyUnavailableError(
            "rate limited", retry_after=JUDGE_WAIT
        )


def activities(
    forge_error: Exception | None = None,
) -> tuple[ReviewActivities, QueryableJournal, InMemorySnapshotStore]:
    journal, snapshots = QueryableJournal(), InMemorySnapshotStore()
    built = ReviewActivities(
        forge=FailingForge(forge_error or ForgeRejectedError("unused")),
        doctrine=FakeDoctrine(),
        judge=RateLimitedJudge(),
        journal=journal,
        snapshots=snapshots,
        archive=InMemoryJudgeArchive(),
        clock=FixedClock(),
        enforcement=gating(),
    )
    return built, journal, snapshots


def observe_request() -> ObservePullRequestRequest:
    return ObservePullRequestRequest(ref=REF, correlation=RUN)


def judge_request(snapshots: InMemorySnapshotStore) -> JudgePullRequestRequest:
    ref = snapshots.put(SNAPSHOT)
    return JudgePullRequestRequest(
        snapshot=SubmissionRef(snapshot_id=ref.snapshot_id, ref=ref.ref),
        corpus=Corpus(doctrine=DoctrineText(text=DOCTRINE.text), judge="j"),
        correlation=RUN,
    )


def publish_request() -> PublishFindingsRequest:
    return PublishFindingsRequest(
        ref=REF,
        findings=(),
        judge_status="skipped: no judge configured",
        corpus_version="v1",
        correlation=RUN,
    )


def test_a_rejected_forge_request_is_not_retried() -> None:
    built, _, _ = activities(ForgeRejectedError("the forge returned 404"))
    with pytest.raises(ApplicationError) as raised:
        at_attempt(1).run(built.observe, observe_request())
    assert raised.value.non_retryable


def test_an_unavailable_forge_is_retried_after_the_wait_it_asked_for() -> None:
    wait = timedelta(seconds=30)
    built, _, _ = activities(ForgeUnavailableError("rate limited", wait))
    with pytest.raises(ApplicationError) as raised:
        at_attempt(1).run(built.observe, observe_request())
    assert not raised.value.non_retryable
    assert raised.value.next_retry_delay == wait


def test_a_rate_limited_judge_with_attempts_left_is_retried() -> None:
    built, journal, snapshots = activities()
    with pytest.raises(ApplicationError) as raised:
        at_attempt(1).run(built.judge, judge_request(snapshots))
    assert not raised.value.non_retryable
    assert raised.value.next_retry_delay == JUDGE_WAIT
    assert journal.entries == []


def test_on_the_last_attempt_a_rate_limited_judge_is_recorded() -> None:
    built, journal, snapshots = activities()
    response = at_attempt(JUDGE_MAX_ATTEMPTS).run(
        built.judge, judge_request(snapshots)
    )
    assert response.status.startswith("unavailable after retries")
    assert [e.event_type for e in journal.entries] == [JUDGE_INVOKED]


def test_an_unavailable_forge_when_publishing_is_retried() -> None:
    wait = timedelta(seconds=5)
    built, _, _ = activities(ForgeUnavailableError("rate limited", wait))
    with pytest.raises(ApplicationError) as raised:
        at_attempt(1).run(built.publish, publish_request())
    assert not raised.value.non_retryable
    assert raised.value.next_retry_delay == wait


def test_a_rejected_write_is_not_retried() -> None:
    built, _, _ = activities(ForgeRejectedError("the forge returned 403"))
    with pytest.raises(ApplicationError) as raised:
        at_attempt(1).run(built.publish, publish_request())
    assert raised.value.non_retryable


def test_a_pull_request_the_forge_will_not_give_is_treated_as_closed() -> None:
    built, _, _ = activities(ForgeRejectedError("the forge returned 404"))
    assert at_attempt(1).run(built.is_open, REF) is False
