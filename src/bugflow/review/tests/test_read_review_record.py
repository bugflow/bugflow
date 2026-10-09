"""Tests of ``ReadReviewRecordUseCase``: the record of one evaluation,
with the judge exchanges it names."""

from typing import Any

from bugflow.review.domain.facts import FINDING_RAISED, JUDGE_INVOKED
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.review.domain.models.recorder import Recorder
from bugflow.review.dtos.read_review_record import ReadReviewRecordRequest
from bugflow.review.infrastructure.in_memory_judge_archive import (
    InMemoryJudgeArchive,
)
from bugflow.review.tests.doubles import NOW
from bugflow.review.tests.journal import QueryableJournal
from bugflow.review.usecases.read_review_record import ReadReviewRecordUseCase
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
    journal, archive = QueryableJournal(), InMemoryJudgeArchive()
    exchange_id = archive.put(EXCHANGE)
    journal.append(
        [
            judged(RUN, "P-01", exchange_id),
            judged(RUN, "P-02", None),
            raised(RUN),
            judged(OTHER, "P-03", None),
            raised(OTHER),
        ]
    )

    response = ReadReviewRecordUseCase(journal, archive).execute(
        ReadReviewRecordRequest(correlation=RUN)
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
    journal = QueryableJournal()
    journal.append([judged(RUN, "P-01", "gone"), judged(RUN, "P-02", "gone")])

    response = ReadReviewRecordUseCase(
        journal, InMemoryJudgeArchive()
    ).execute(ReadReviewRecordRequest(correlation=RUN))

    assert response.missing_exchanges == ("gone",)
    assert response.record.policies[0].exchange_id == "gone"
    assert response.record.policies[0].exchange is None


def test_a_run_with_no_entries_gives_an_empty_record() -> None:
    response = ReadReviewRecordUseCase(
        QueryableJournal(), InMemoryJudgeArchive()
    ).execute(ReadReviewRecordRequest(correlation=RUN))

    assert response.record.findings == ()
    assert response.record.pr_number is None
