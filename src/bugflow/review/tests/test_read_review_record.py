"""Tests of ``ReadReviewRecordUseCase``: the record of one evaluation,
with the judge exchanges it names."""

import json
from dataclasses import asdict, replace
from typing import Any

import pytest

from bugflow.review.domain.errors import (
    HistoryTooLargeError,
    ReviewRecordNotFoundError,
    SubmissionNotFoundError,
)
from bugflow.review.domain.facts import FINDING_RAISED, JUDGE_INVOKED
from bugflow.review.domain.models.history import (
    HistoryLimits,
    StoredReviewEvent,
)
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.review.domain.models.recorder import Recorder
from bugflow.review.domain.models.submission import Submission, SubmissionRef
from bugflow.review.dtos.read_review_record import ReadReviewRecordRequest
from bugflow.review.infrastructure.in_memory_history import InMemoryHistory
from bugflow.review.infrastructure.in_memory_judge_archive import (
    InMemoryJudgeArchive,
)
from bugflow.review.tests.doubles import NOW
from bugflow.review.usecases.read_review_record import ReadReviewRecordUseCase
from bugflow.shared.domain.errors import ContentTooLargeError
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="orchard", repo="pear-tree", number=5)
RUN = Correlation(workflow_id="pr/5", run_id="run-1")
OTHER = Correlation(workflow_id="pr/5", run_id="run-2")
EXCHANGE = JudgeExchange(request={"policy": "P-01"}, response={"ok": True})


def judged(
    run: Correlation, policy: str, exchange_id: str | None
) -> JournalEntry:
    identity: dict[str, Any] | None = (
        {"exchange_id": exchange_id} if exchange_id else None
    )
    return Recorder(REF, run, "server-1", NOW).entry(
        JUDGE_INVOKED,
        f"judge/{policy}",
        {
            "policy_id": policy,
            "status": "judged by a-model",
            "model": "a-model",
            "finding_count": 0,
            "identity": identity,
        },
    )


def raised(run: Correlation) -> JournalEntry:
    return Recorder(REF, run, "server-1", NOW).entry(
        FINDING_RAISED,
        "judged/0/P-01/pull request",
        {
            "policy_id": "P-01",
            "clause": "RULE-1",
            "subject": "pull request",
            "severity": "warn",
            "message": "a message",
        },
    )


def test_the_record_has_the_runs_entries_and_its_stored_exchanges() -> None:
    journal, archive = InMemoryHistory(), InMemoryJudgeArchive()
    exchange_id = archive.put(EXCHANGE)
    journal = InMemoryHistory(
        [
            StoredReviewEvent(entry=e)
            for e in [
                judged(RUN, "P-01", exchange_id),
                judged(RUN, "P-02", None),
                raised(RUN),
                judged(OTHER, "P-03", None),
                raised(OTHER),
            ]
        ]
    )

    response = ReadReviewRecordUseCase(journal, archive).execute(
        ReadReviewRecordRequest(ref=REF, correlation=RUN)
    )

    record = response.record
    assert record.correlation == RUN
    assert (record.repo, record.pr_number) == ("orchard/pear-tree", 5)
    assert [p.policy_id for p in record.policies] == ["P-01", "P-02"]
    assert record.policies[0].exchange == EXCHANGE
    assert record.policies[1].exchange is None
    assert len(record.findings) == 1
    assert response.missing_exchanges == ()


def test_an_exchange_the_store_no_longer_has_is_listed_as_missing() -> None:
    journal = InMemoryHistory()
    journal = InMemoryHistory(
        [
            StoredReviewEvent(entry=e)
            for e in [judged(RUN, "P-01", "gone"), judged(RUN, "P-02", "gone")]
        ]
    )

    response = ReadReviewRecordUseCase(
        journal, InMemoryJudgeArchive()
    ).execute(ReadReviewRecordRequest(ref=REF, correlation=RUN))

    assert response.missing_exchanges == ("gone",)
    assert response.record.policies[0].exchange_id == "gone"
    assert response.record.policies[0].exchange is None


def test_a_run_with_no_scoped_entries_is_not_found() -> None:
    with pytest.raises(ReviewRecordNotFoundError):
        ReadReviewRecordUseCase(
            InMemoryHistory(), InMemoryJudgeArchive()
        ).execute(ReadReviewRecordRequest(ref=REF, correlation=RUN))


class Submissions:
    def __init__(self, content: dict[SubmissionRef, Submission]) -> None:
        self.content = content
        self.read: list[SubmissionRef] = []

    def get_bounded(
        self, reference: SubmissionRef, max_bytes: int
    ) -> tuple[Submission, int]:
        self.read.append(reference)
        try:
            submission = self.content[reference]
        except KeyError as exc:
            raise SubmissionNotFoundError from exc
        size = len(
            json.dumps(asdict(submission), ensure_ascii=False).encode("utf-8")
        )
        if size > max_bytes:
            raise ContentTooLargeError("submission exceeds byte limit")
        return submission, size


def observed(snapshot_id: str | None) -> JournalEntry:
    return Recorder(REF, RUN, "server-1", NOW).entry(
        "pr.observed", "observed", {"snapshot_id": snapshot_id}
    )


def history(*entries: JournalEntry) -> InMemoryHistory:
    return InMemoryHistory([StoredReviewEvent(entry=e) for e in entries])


def test_detail_reads_only_content_named_by_the_scoped_run() -> None:
    archive = InMemoryJudgeArchive()
    first = archive.put(EXCHANGE)
    foreign = archive.put(
        JudgeExchange(request={"private": True}, response={})
    )
    own = judged(RUN, "P-01", first)
    other_repo = replace(judged(RUN, "P-02", foreign), repo="another/private")
    other_pr = replace(judged(RUN, "P-03", foreign), pr_number=77)
    other_run = judged(OTHER, "P-04", foreign)
    content = Submission(title="read", body="retained", commits=(), files=())
    reference = SubmissionRef(snapshot_id="snapshot", ref=REF)
    submissions = Submissions({reference: content})
    response = ReadReviewRecordUseCase(
        history(own, other_repo, other_pr, other_run, observed("snapshot")),
        archive,
        submissions,
    ).execute(ReadReviewRecordRequest(ref=REF, correlation=RUN))
    assert [p.policy_id for p in response.record.policies] == ["P-01"]
    assert response.record.policies[0].exchange == EXCHANGE
    assert response.submissions == {"snapshot": content}
    assert submissions.read == [reference]
    assert foreign not in response.model_dump_json()
    assert {
        r.availability for r in response.content_references if r.content_id
    } == {"available"}


def test_missing_content_differs_from_no_recorded_reference() -> None:
    response = ReadReviewRecordUseCase(
        history(observed("gone"), judged(RUN, "P-01", None)),
        InMemoryJudgeArchive(),
        Submissions({}),
    ).execute(ReadReviewRecordRequest(ref=REF, correlation=RUN))
    assert response.missing_submissions == ("gone",)
    assert response.missing_exchanges == ()
    assert {r.availability for r in response.content_references} == {
        "missing",
        "not_recorded",
    }


def test_unconfigured_submission_source_does_not_claim_missing_content() -> (
    None
):
    response = ReadReviewRecordUseCase(
        history(observed("not-read")), InMemoryJudgeArchive()
    ).execute(ReadReviewRecordRequest(ref=REF, correlation=RUN))
    assert response.missing_submissions == ()
    assert response.content_references[0].availability == "not_checked"


def test_wrong_repository_is_refused_before_any_content_read() -> None:
    class UnreadArchive(InMemoryJudgeArchive):
        def get_bounded(
            self, exchange_id: str, max_bytes: int
        ) -> tuple[JudgeExchange, int]:
            pytest.fail("content read outside the requested repository")

    with pytest.raises(ReviewRecordNotFoundError):
        ReadReviewRecordUseCase(
            history(
                replace(judged(RUN, "P-01", "private"), repo="other/private")
            ),
            UnreadArchive(),
        ).execute(ReadReviewRecordRequest(ref=REF, correlation=RUN))


def test_detail_is_refused_when_linked_content_exceeds_the_byte_limit() -> (
    None
):
    archive = InMemoryJudgeArchive()
    exchange_id = archive.put(
        JudgeExchange(request={"text": "x" * 20_000}, response={})
    )
    with pytest.raises(HistoryTooLargeError):
        ReadReviewRecordUseCase(
            history(judged(RUN, "P-01", exchange_id)),
            archive,
            limits=HistoryLimits(max_bytes=10_000),
        ).execute(ReadReviewRecordRequest(ref=REF, correlation=RUN))


def test_detail_shares_the_allowance_across_linked_content() -> None:
    archive = InMemoryJudgeArchive()
    exchange = JudgeExchange(request={"text": "x" * 7000}, response={})
    exchange_id = archive.put(exchange)
    _, charge = archive.get_bounded(exchange_id, 10_000)
    content = Submission(
        title="snapshot", body="y" * 4000, commits=(), files=()
    )
    reference = SubmissionRef(snapshot_id="snapshot", ref=REF)

    class MeasuredSubmissions(Submissions):
        allowance: int | None = None

        def get_bounded(
            self, reference: SubmissionRef, max_bytes: int
        ) -> tuple[Submission, int]:
            self.allowance = max_bytes
            return super().get_bounded(reference, max_bytes)

    submissions = MeasuredSubmissions({reference: content})
    # Each item fits separately; the second must see the charge for the first.
    submissions.get_bounded(reference, 10_000)
    with pytest.raises(HistoryTooLargeError):
        ReadReviewRecordUseCase(
            history(judged(RUN, "P-01", exchange_id), observed("snapshot")),
            archive,
            submissions,
            HistoryLimits(max_bytes=10_000),
        ).execute(ReadReviewRecordRequest(ref=REF, correlation=RUN))
    assert submissions.allowance == 10_000 - charge
