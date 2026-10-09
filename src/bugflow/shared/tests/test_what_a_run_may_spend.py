"""Tests of budgets: how several limits combine into what one run may
spend, and how the period containing a moment is found."""

from datetime import UTC, datetime

import pytest

from bugflow.shared.domain.values.budget import Budget, allowance, period

REPOSITORY = Budget(usd=10.0, turns=100.0)
REVIEWER = Budget(usd=5.0, turns=200.0)
DECLARED = Budget(usd=9.0, turns=120.0)
UNLIMITED = Budget(usd=None, turns=None)


def test_nothing_granted_allows_nothing() -> None:
    assert allowance((), None) is None


def test_a_declared_figure_grants_nothing_by_itself() -> None:
    assert allowance((), DECLARED) is None


def test_one_granted_budget_is_what_a_run_may_spend() -> None:
    assert allowance([REPOSITORY], None) == REPOSITORY


def test_every_granted_budget_applies_and_the_lowest_holds() -> None:
    """The repository allows ten dollars and a hundred turns, and the
    reviewer five dollars and two hundred turns. A run must stay within
    both, so it gets five dollars and a hundred turns."""
    assert allowance([REPOSITORY, REVIEWER], None) == Budget(
        usd=5.0, turns=100.0
    )


def test_a_declared_figure_lowers_what_was_granted() -> None:
    assert allowance([REPOSITORY], DECLARED) == Budget(usd=9.0, turns=100.0)
    assert allowance(
        [REPOSITORY, REVIEWER], Budget(usd=1.0, turns=10.0)
    ) == Budget(usd=1.0, turns=10.0)


def test_a_declared_figure_does_not_raise_what_was_granted() -> None:
    assert allowance([Budget(usd=2.0, turns=30.0)], DECLARED) == Budget(
        usd=2.0, turns=30.0
    )


def test_a_budget_may_limit_nothing() -> None:
    """A budget with no limits is still something granted, unlike no
    budget at all, which allows nothing."""
    assert allowance([UNLIMITED], None) == UNLIMITED


def test_an_unlimited_budget_beside_a_limit_changes_nothing() -> None:
    assert allowance([UNLIMITED, REPOSITORY], None) == REPOSITORY


def test_each_resource_is_limited_separately() -> None:
    assert allowance([Budget(usd=None, turns=60.0)], None) == Budget(
        usd=None, turns=60.0
    )
    assert allowance(
        [Budget(usd=None, turns=60.0), Budget(usd=10.0, turns=None)], None
    ) == Budget(usd=10.0, turns=60.0)


WEDNESDAY = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)


def test_a_week_runs_from_where_the_caller_says() -> None:
    """Weeks that begin on a Wednesday at nine: a moment on the next
    Tuesday is still in the first week."""
    assert period("week", WEDNESDAY, datetime(2026, 9, 8, tzinfo=UTC)) == (
        WEDNESDAY,
        datetime(2026, 9, 9, 9, 0, tzinfo=UTC),
    )
    assert period(
        "week", WEDNESDAY, datetime(2026, 9, 9, 9, 0, tzinfo=UTC)
    ) == (
        datetime(2026, 9, 9, 9, 0, tzinfo=UTC),
        datetime(2026, 9, 16, 9, 0, tzinfo=UTC),
    )


def test_periods_are_counted_backwards_from_a_later_start() -> None:
    assert period("day", WEDNESDAY, datetime(2026, 8, 31, 12, tzinfo=UTC)) == (
        datetime(2026, 8, 31, 9, 0, tzinfo=UTC),
        datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
    )


def test_months_are_calendar_months() -> None:
    first = datetime(2026, 1, 15, tzinfo=UTC)

    assert period("month", first, datetime(2026, 3, 20, tzinfo=UTC)) == (
        datetime(2026, 3, 15, tzinfo=UTC),
        datetime(2026, 4, 15, tzinfo=UTC),
    )
    assert period("quarter", first, datetime(2026, 3, 20, tzinfo=UTC)) == (
        first,
        datetime(2026, 4, 15, tzinfo=UTC),
    )
    assert period("year", first, datetime(2025, 6, 1, tzinfo=UTC)) == (
        datetime(2025, 1, 15, tzinfo=UTC),
        first,
    )


def test_no_span_means_no_period() -> None:
    assert period("", WEDNESDAY, WEDNESDAY) is None


def test_an_unknown_span_is_refused() -> None:
    with pytest.raises(ValueError, match="no span"):
        period("decade", WEDNESDAY, WEDNESDAY)
