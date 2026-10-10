"""Tests of what a dispatch hands the runner, and when it hands it
nothing.

A deployment that has bound nothing dispatches nothing. A repository
with no activities spends no money, and a repository with activities
and no budget spends no money either.
"""

from bugflow.apps.worker.reviewers import ReviewerSettings, allowance_for
from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.infrastructure.in_memory_spend_bindings import (
    InMemorySpendBindings,
)
from bugflow.shared.domain.values.budget import Budget

BOUND = Budget(usd=10.0, turns=100.0)
WORTH = Budget(usd=9.0, turns=120.0)


def settings(worth: Budget | None = None) -> ReviewerSettings:
    return ReviewerSettings(
        agent_id="security",
        instructions="Read the week.",
        worth=worth,
        layer="weekly",
    )


def bound(scope: SpendScope) -> InMemorySpendBindings:
    held = InMemorySpendBindings()
    held.declare(SpendBinding(scope=scope, budget=BOUND))
    return held


def test_a_deployment_with_no_bindings_allows_nothing() -> None:
    assert allowance_for(None, "github", "o/r", settings()) is None


def test_a_repository_nothing_was_bound_for_allows_nothing() -> None:
    held = InMemorySpendBindings()
    assert allowance_for(held, "github", "o/r", settings()) is None


def test_what_the_deployment_bound_is_what_the_dispatch_gets() -> None:
    held = bound(SpendScope(forge="github", repo="o/r"))
    assert allowance_for(held, "github", "o/r", settings()) == BOUND


def test_what_the_process_declared_caps_it() -> None:
    held = bound(SpendScope(forge="github", repo="o/r"))
    found = allowance_for(held, "github", "o/r", settings(WORTH))
    assert found == Budget(usd=9.0, turns=100.0)


def test_a_binding_for_another_repository_allows_nothing() -> None:
    held = bound(SpendScope(forge="github", repo="o/other"))
    assert allowance_for(held, "github", "o/r", settings()) is None


def test_a_binding_scoped_to_this_layer_and_agent_is_used() -> None:
    held = bound(
        SpendScope(
            forge="github",
            repo="o/r",
            layer="weekly",
            agent_id="security",
        )
    )
    assert allowance_for(held, "github", "o/r", settings()) == BOUND


def test_a_binding_scoped_to_another_layer_allows_nothing() -> None:
    held = bound(SpendScope(forge="github", repo="o/r", layer="pull-request"))
    assert allowance_for(held, "github", "o/r", settings()) is None


def test_a_run_is_held_to_the_lowest_of_every_binding() -> None:
    """The repository allows ten dollars, the reviewer five. A run gets
    five, because both bindings apply and it must satisfy each."""
    held = InMemorySpendBindings()
    held.declare(
        SpendBinding(
            scope=SpendScope(forge="github", repo="o/r"), budget=BOUND
        )
    )
    held.declare(
        SpendBinding(
            scope=SpendScope(
                forge="github",
                repo="o/r",
                layer="weekly",
                agent_id="security",
            ),
            budget=Budget(usd=5.0, turns=200.0),
        )
    )
    found = allowance_for(held, "github", "o/r", settings())
    assert found == Budget(usd=5.0, turns=100.0)


def test_a_period_allowance_does_not_become_a_runs_ceiling() -> None:
    """A week's allowance is not what one review may spend, so a run
    matched only by a period binding is allowed nothing and not the
    week."""
    held = InMemorySpendBindings()
    held.declare(
        SpendBinding(
            scope=SpendScope(forge="github", repo="o/r"),
            budget=Budget(usd=50.0, turns=0.0),
            per="week",
        )
    )
    assert allowance_for(held, "github", "o/r", settings()) is None
