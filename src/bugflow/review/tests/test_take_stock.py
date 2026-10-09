"""Tests of ``TakeStockUseCase``: the range a stocktake covers and the
mark it leaves."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from bugflow.review.dtos.take_stock import (
    TakeStockRequest,
    TakeStockResponse,
)
from bugflow.review.tests.journal import QueryableJournal
from bugflow.review.usecases.take_stock import TakeStockUseCase
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(forge="github", owner="o", repo="r", number=0)
SUNDAY = datetime(2030, 9, 27, 13, 30, tzinfo=UTC)
RUN = Correlation(workflow_id="stocktake/github/o/r/weekly", run_id="s-1")


class Clock:
    def now(self) -> datetime:
        return SUNDAY


def merged(pr: int, at: datetime) -> JournalEntry:
    return JournalEntry(
        event_id=uuid4(),
        occurred_at=at,
        event_type="pr.merged",
        forge=REF.forge,
        repo=f"{REF.owner}/{REF.repo}",
        pr_number=pr,
        commit_sha="a" * 40,
        corpus_version=None,
        workflow_id=f"pr/github/o/r/{pr}",
        run_id=f"e-{pr}",
        payload={"delivery_id": "d"},
    )


def take(
    *entries: JournalEntry, run: Correlation = RUN
) -> tuple[TakeStockResponse, QueryableJournal]:
    journal = QueryableJournal()
    journal.append(list(entries))
    response = TakeStockUseCase(journal, Clock()).execute(
        TakeStockRequest(
            forge=REF.forge,
            repo=f"{REF.owner}/{REF.repo}",
            layer="weekly",
            correlation=run,
        )
    )
    return response, journal


def test_the_first_stocktake_reads_everything_and_marks_it() -> None:
    response, journal = take(merged(1, SUNDAY - timedelta(days=30)))
    assert response.merged == 1 and response.worth_taking
    (mark,) = [e for e in journal.entries if e.event_type == "stocktake.taken"]
    assert mark.payload["layer"] == "weekly"
    assert mark.payload["merged"] == 1


def test_the_next_stocktake_starts_at_the_last_mark() -> None:
    first, journal = take(
        merged(1, SUNDAY - timedelta(days=9)),
        merged(2, SUNDAY - timedelta(days=1)),
    )
    assert first.merged == 2
    later = TakeStockUseCase(journal, Clock()).execute(
        TakeStockRequest(
            forge=REF.forge,
            repo=f"{REF.owner}/{REF.repo}",
            layer="weekly",
            correlation=Correlation(workflow_id=RUN.workflow_id, run_id="s-2"),
        )
    )
    assert later.merged == 0 and not later.worth_taking


def test_a_quiet_range_still_leaves_a_mark() -> None:
    response, journal = take()
    assert not response.worth_taking
    assert [e.event_type for e in journal.entries] == ["stocktake.taken"]


def test_another_layers_mark_is_not_this_layers() -> None:
    _, journal = take()
    weekly = TakeStockUseCase(journal, Clock()).execute(
        TakeStockRequest(
            forge=REF.forge,
            repo=f"{REF.owner}/{REF.repo}",
            layer="monthly",
            correlation=Correlation(
                workflow_id="stocktake/github/o/r/monthly", run_id="m-1"
            ),
        )
    )
    assert weekly.since is None


def test_the_mark_carries_the_commit_the_next_range_diffs_from() -> None:
    response, journal = take(merged(1, SUNDAY - timedelta(days=2)))
    assert response.head_sha == "a" * 40
    (mark,) = [e for e in journal.entries if e.event_type == "stocktake.taken"]
    assert mark.payload["head_sha"] == "a" * 40

    later = TakeStockUseCase(journal, Clock()).execute(
        TakeStockRequest(
            forge=REF.forge,
            repo=f"{REF.owner}/{REF.repo}",
            layer="weekly",
            correlation=Correlation(workflow_id=RUN.workflow_id, run_id="s-2"),
        )
    )
    assert later.base_sha == "a" * 40 and later.head_sha is None
