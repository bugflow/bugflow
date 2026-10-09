"""Tests of ``stocktake_range``: which merged pull requests a stocktake
covers."""

from datetime import UTC, datetime, timedelta

from bugflow.review.domain.models.stocktake import (
    Mark,
    Merged,
    stocktake_range,
)

SUNDAY = datetime(2030, 9, 27, 13, 30, tzinfo=UTC)
WEEK_BEFORE = SUNDAY - timedelta(days=7)


def merged(at: datetime, pr: int = 1) -> Merged:
    return Merged(pull_request=pr, head_sha="a" * 40, merged_at=at)


def test_the_first_stocktake_of_a_layer_takes_everything() -> None:
    taken = stocktake_range(
        now=SUNDAY, mark=None, merged=[merged(WEEK_BEFORE - timedelta(days=3))]
    )
    assert (taken.since, taken.until) == (None, SUNDAY)
    assert len(taken.merged) == 1


def test_a_later_stocktake_starts_where_the_last_one_stopped() -> None:
    inside = merged(SUNDAY - timedelta(days=2), pr=2)
    before = merged(WEEK_BEFORE - timedelta(days=1), pr=1)
    taken = stocktake_range(
        now=SUNDAY,
        mark=Mark(taken_at=WEEK_BEFORE),
        merged=[before, inside],
    )
    assert [m.pull_request for m in taken.merged] == [2]
    assert taken.since == WEEK_BEFORE


def test_a_range_with_nothing_merged_is_not_worth_reviewing() -> None:
    quiet = stocktake_range(
        now=SUNDAY, mark=Mark(taken_at=WEEK_BEFORE), merged=[]
    )
    assert quiet.merged == () and not quiet.worth_taking


def test_a_range_with_something_merged_is_worth_reviewing() -> None:
    busy = stocktake_range(
        now=SUNDAY,
        mark=Mark(taken_at=WEEK_BEFORE),
        merged=[merged(SUNDAY - timedelta(hours=1))],
    )
    assert busy.worth_taking


def test_what_merged_is_ordered_as_it_happened() -> None:
    first = merged(SUNDAY - timedelta(days=3), pr=1)
    second = merged(SUNDAY - timedelta(days=1), pr=2)
    taken = stocktake_range(now=SUNDAY, mark=None, merged=[second, first])
    assert [m.pull_request for m in taken.merged] == [1, 2]


def test_a_range_is_two_commits_a_review_can_diff() -> None:
    taken = stocktake_range(
        now=SUNDAY,
        mark=Mark(taken_at=WEEK_BEFORE, head_sha="b" * 40),
        merged=[
            merged(SUNDAY - timedelta(days=2), pr=2),
            merged(SUNDAY - timedelta(hours=2), pr=3),
        ],
    )
    assert taken.base_sha == "b" * 40
    assert taken.head_sha == "a" * 40


def test_the_first_range_has_no_base_to_diff_from() -> None:
    taken = stocktake_range(now=SUNDAY, mark=None, merged=[merged(SUNDAY)])
    assert taken.base_sha is None and taken.head_sha == "a" * 40


def test_an_empty_range_has_no_head() -> None:
    taken = stocktake_range(
        now=SUNDAY,
        mark=Mark(taken_at=WEEK_BEFORE, head_sha="b" * 40),
        merged=[],
    )
    assert taken.head_sha is None
