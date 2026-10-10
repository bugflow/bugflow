"""Tests of what a deployment lets a run spend, kept in memory.

They ask the same questions as the tests of the Postgres adapter in
``test_sqlalchemy_spend_bindings.py``, so that the two cannot drift.

Every binding that matches is answered and all of them apply: a run
must satisfy each. The narrowest comes first for a reader's
convenience and takes no precedence.
"""

from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.infrastructure.in_memory_spend_bindings import (
    InMemorySpendBindings,
)
from bugflow.shared.domain.values.budget import Budget

REPO = SpendScope(forge="github", repo="o/r")
WEEKLY = SpendScope(
    forge="github", repo="o/r", layer="weekly", agent_id="security"
)


def bindings(*bound: tuple[SpendScope, float]) -> InMemorySpendBindings:
    held = InMemorySpendBindings()
    for scope, usd in bound:
        held.declare(
            SpendBinding(scope=scope, budget=Budget(usd=usd, turns=10))
        )
    return held


def allowed(
    held: InMemorySpendBindings,
    repo: str = "o/r",
    layer: str = "weekly",
    agent: str = "security",
) -> list[float | None]:
    return [
        one.budget.usd
        for one in held.binding_for("github", repo, layer, agent)
    ]


def test_a_ceiling_bound_to_a_repository_applies_to_it() -> None:
    assert allowed(bindings((REPO, 2.5))) == [2.5]


def test_a_scope_nothing_bound_is_allowed_nothing() -> None:
    """Empty rather than a figure: silence is not consent."""
    assert allowed(InMemorySpendBindings()) == []


def test_every_binding_that_matches_is_answered() -> None:
    """Both apply and a run must satisfy each."""
    held = bindings((REPO, 2.5), (WEEKLY, 9.0))
    assert allowed(held) == [9.0, 2.5]
    assert allowed(held, layer="pull-request", agent="n") == [2.5]


def test_one_repositorys_ceiling_is_not_anothers() -> None:
    assert allowed(bindings((REPO, 2.5)), repo="o/other") == []


def test_declaring_a_scope_twice_replaces_its_ceiling() -> None:
    assert allowed(bindings((REPO, 2.5), (REPO, 7.0))) == [7.0]


def test_every_ceiling_can_be_listed_most_specific_first() -> None:
    held = bindings((REPO, 2.5), (WEEKLY, 9.0))
    assert [one.scope.parts for one in held.bindings()] == [4, 2]


def test_a_ceiling_bound_to_nothing_covers_everything() -> None:
    """One row caps the whole deployment, which is what a deployment
    reaching for this at two in the morning wants first."""
    assert allowed(bindings((SpendScope(), 1.0))) == [1.0]


def test_a_binding_says_what_shares_it_and_defaults_to_one_run() -> None:
    held = bindings((REPO, 2.5))
    (one,) = held.bindings()
    assert one.per == "event"


def test_a_weekly_allowance_is_the_same_object() -> None:
    held = InMemorySpendBindings()
    held.declare(
        SpendBinding(
            scope=REPO, budget=Budget(usd=50.0, turns=0), per="weekly"
        )
    )
    (one,) = held.bindings()
    assert (one.per, one.budget.usd) == ("weekly", 50.0)


def test_one_scope_holds_an_allowance_per_denominator() -> None:
    held = InMemorySpendBindings()
    held.declare(SpendBinding(scope=REPO, budget=Budget(usd=2.5, turns=60)))
    held.declare(
        SpendBinding(
            scope=REPO, budget=Budget(usd=10.0, turns=None), per="nightly"
        )
    )
    assert {one.per for one in held.bindings()} == {"event", "nightly"}


def test_revoking_one_leaves_the_other() -> None:
    """Removing is not binding zero: zero refuses everything, and
    removing leaves the scope to whatever wider allowance covers it."""
    held = InMemorySpendBindings()
    held.declare(SpendBinding(scope=REPO, budget=Budget(usd=2.5, turns=60)))
    held.declare(
        SpendBinding(
            scope=REPO, budget=Budget(usd=10.0, turns=None), per="nightly"
        )
    )
    held.revoke(REPO, "nightly")
    assert [(one.per, one.budget.usd) for one in held.bindings()] == [
        ("event", 2.5)
    ]


def test_revoking_what_was_never_bound_changes_nothing() -> None:
    held = InMemorySpendBindings()
    held.declare(SpendBinding(scope=REPO, budget=Budget(usd=2.5, turns=60)))
    held.revoke(WEEKLY, "nightly")
    assert len(held.bindings()) == 1
