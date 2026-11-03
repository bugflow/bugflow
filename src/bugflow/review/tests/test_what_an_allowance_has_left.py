"""What an allowance has left in its period, and when it has no room.

The dispatcher and a page read the same figure, so these are the rules
both follow.
"""

from datetime import UTC, datetime, timedelta

from bugflow.review.domain.models.remaining import Remaining
from bugflow.review.domain.models.spend import Spent
from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.shared.domain.values.budget import Budget

SINCE = datetime(2026, 11, 2, tzinfo=UTC)
UNTIL = SINCE + timedelta(days=7)


def left(allowed: float | None, spent: float) -> Remaining:
    return Remaining(
        binding=SpendBinding(
            scope=SpendScope(forge="github", repo="o/r"),
            budget=Budget(usd=allowed),
            per="week",
        ),
        spent=Spent(
            forge="github",
            repo="o/r",
            layer="",
            agent_id="",
            since=SINCE,
            until=UNTIL,
            usd=spent,
            facts=1,
        ),
    )


def test_what_is_left_is_the_allowance_less_the_spend() -> None:
    remaining = left(10.0, 4.0)
    assert (remaining.left_usd, remaining.over_usd, remaining.has_room) == (
        6.0,
        0.0,
        True,
    )


def test_an_overspent_allowance_has_nothing_left_and_says_by_how_much() -> (
    None
):
    remaining = left(10.0, 12.5)
    assert (remaining.left_usd, remaining.over_usd, remaining.has_room) == (
        0.0,
        2.5,
        False,
    )


def test_an_allowance_spent_exactly_has_no_room() -> None:
    assert not left(10.0, 10.0).has_room


def test_no_money_limit_leaves_no_figure_and_always_has_room() -> None:
    remaining = left(None, 1000.0)
    assert (remaining.left_usd, remaining.has_room) == (None, True)


def test_what_is_left_states_its_period() -> None:
    assert (left(10.0, 4.0).since, left(10.0, 4.0).until) == (SINCE, UNTIL)
