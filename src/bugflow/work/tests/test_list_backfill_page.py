"""Tests of ``ListBackfillPageUseCase``: a page of closed pull requests,
without the ones the backfill has already done."""

from datetime import UTC, datetime
from typing import Literal

import pytest

from bugflow.shared.domain.models.recorder import Recorder
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.work.domain.facts import JUDGE_INVOKED, PR_OBSERVED
from bugflow.work.domain.models.backfill import (
    BackfillCandidate,
    BackfillPage,
)
from bugflow.work.dtos.list_backfill_page import (
    BackfillPullRequest,
    ListBackfillPageRequest,
)
from bugflow.work.tests.journal import QueryableJournal
from bugflow.work.usecases.list_backfill_page import ListBackfillPageUseCase

AT = datetime(2030, 3, 12, tzinfo=UTC)
NOT_JUDGED = "skipped: judging is switched off for this run"
JUDGED = "judged by a model"


def closed(
    number: int,
    head: str,
    forge: Literal["github", "forgejo"] = "github",
) -> BackfillCandidate:
    return BackfillCandidate(
        ref=PullRequestRef(
            forge=forge, owner="orchard", repo="pear-tree", number=number
        ),
        head_sha=head,
    )


class FakeFeed:
    """Returns the same page whatever it is asked, and records what it
    was asked."""

    def __init__(self, *pulls: BackfillCandidate, last: bool = True) -> None:
        self.page = BackfillPage(pulls=pulls, last=last)
        self.asked: list[tuple[str, str, int]] = []

    def closed_pull_requests(
        self, owner: str, repo: str, page: int
    ) -> BackfillPage:
        self.asked.append((owner, repo, page))
        return self.page


def reviewed(
    journal: QueryableJournal,
    ref: PullRequestRef,
    head: str,
    judge: str = NOT_JUDGED,
) -> None:
    """Write the entries one workflow run leaves when it reviews the
    pull request at commit ``head``: a snapshot taken, and what the
    judge did."""
    run = Correlation(workflow_id=f"w/{ref.number}", run_id=f"run/{head[:4]}")
    recorder = Recorder(ref, run, None, AT)
    journal.append(
        [
            recorder.entry(PR_OBSERVED, head, {}, commit_sha=head),
            recorder.entry(JUDGE_INVOKED, "judge/P-01", {"status": judge}),
        ]
    )


def listed(
    journal: QueryableJournal, feed: FakeFeed, use_judge: bool
) -> tuple[int, ...]:
    response = ListBackfillPageUseCase({"github": feed}, journal).execute(
        ListBackfillPageRequest(
            repository="orchard/pear-tree", use_judge=use_judge
        )
    )
    return tuple(p.ref.number for p in response.pulls)


def test_a_pull_request_reviewed_at_its_last_commit_is_left_out() -> None:
    journal = QueryableJournal()
    seen = closed(1, "a" * 40)
    moved = closed(2, "c" * 40)
    fresh = closed(3, "d" * 40)
    reviewed(journal, seen.ref, "a" * 40)
    reviewed(journal, moved.ref, "b" * 40)
    feed = FakeFeed(seen, moved, fresh)

    response = ListBackfillPageUseCase({"github": feed}, journal).execute(
        ListBackfillPageRequest(repository="orchard/pear-tree", page=2)
    )

    assert feed.asked == [("orchard", "pear-tree", 2)]
    assert response.pulls == (
        BackfillPullRequest(ref=moved.ref, head_sha="c" * 40),
        BackfillPullRequest(ref=fresh.ref, head_sha="d" * 40),
    )
    assert (response.already_observed, response.last) == (1, True)


def test_the_feed_for_the_repositorys_forge_is_asked() -> None:
    github = FakeFeed()
    forgejo = FakeFeed(closed(1, "a" * 40, "forgejo"), last=False)

    response = ListBackfillPageUseCase(
        {"github": github, "forgejo": forgejo}, QueryableJournal()
    ).execute(ListBackfillPageRequest(repository="forgejo:orchard/pear-tree"))

    assert github.asked == []
    assert forgejo.asked == [("orchard", "pear-tree", 1)]
    assert response.last is False
    assert response.pulls[0].ref.forge == "forgejo"


def test_a_forge_with_no_feed_is_refused() -> None:
    with pytest.raises(ValueError, match="no forgejo forge"):
        ListBackfillPageUseCase({}, QueryableJournal()).execute(
            ListBackfillPageRequest(repository="forgejo:orchard/pear-tree")
        )


def test_a_review_without_judging_does_not_count_for_a_judging_backfill() -> (
    None
):
    journal = QueryableJournal()
    seen = closed(1, "a" * 40)
    reviewed(journal, seen.ref, "a" * 40)

    assert listed(journal, FakeFeed(seen), use_judge=False) == ()
    assert listed(journal, FakeFeed(seen), use_judge=True) == (1,)


def test_a_judged_review_counts_for_both_kinds_of_backfill() -> None:
    journal = QueryableJournal()
    seen = closed(1, "a" * 40)
    reviewed(journal, seen.ref, "a" * 40, judge=JUDGED)

    assert listed(journal, FakeFeed(seen), use_judge=False) == ()
    assert listed(journal, FakeFeed(seen), use_judge=True) == ()


def test_a_pull_request_the_judge_could_not_answer_is_listed_again() -> None:
    journal = QueryableJournal()
    done, stopped = closed(1, "a" * 40), closed(2, "b" * 40)
    reviewed(journal, done.ref, "a" * 40, judge=JUDGED)
    reviewed(
        journal,
        stopped.ref,
        "b" * 40,
        judge="unavailable: the daily quota is used up",
    )

    assert listed(journal, FakeFeed(done, stopped), use_judge=True) == (2,)


def test_a_judgement_of_an_earlier_commit_does_not_count() -> None:
    journal = QueryableJournal()
    moved = closed(1, "b" * 40)
    reviewed(journal, moved.ref, "a" * 40, judge=JUDGED)

    assert listed(journal, FakeFeed(moved), use_judge=True) == (1,)
