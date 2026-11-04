"""Allowing a scope to spend per a cadence, and revoking it: every change
is journalled with who made it and what it replaced, and a declaration
that changes nothing writes nothing."""

from datetime import UTC, datetime

from bugflow.review.domain.facts import ALLOWANCE_DECLARED
from bugflow.review.domain.models.spend_binding import SpendScope
from bugflow.review.dtos.declare_allowance import DeclareAllowanceRequest
from bugflow.review.infrastructure.in_memory_spend_bindings import (
    InMemorySpendBindings,
)
from bugflow.review.usecases.declare_allowance import (
    DeclareAllowanceUseCase,
)
from bugflow.shared.domain.values.budget import Budget
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal

SCOPE = SpendScope(forge="github", repo="o/r", agent_id="safety")
AT = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return AT


def declaring() -> tuple[
    DeclareAllowanceUseCase, InMemorySpendBindings, InMemoryJournal
]:
    bindings, journal = InMemorySpendBindings(), InMemoryJournal()
    return (
        DeclareAllowanceUseCase(bindings, journal, Clock(), "run-1"),
        bindings,
        journal,
    )


def allow(budget: Budget | None, per: str = "week") -> DeclareAllowanceRequest:
    return DeclareAllowanceRequest(
        scope=SCOPE, per=per, budget=budget, declared_by="someone@example"
    )


def test_an_allowance_is_journalled_with_who_and_what_it_replaced() -> None:
    use_case, bindings, journal = declaring()
    use_case.execute(allow(Budget(usd=2.0, turns=None)))
    declared = use_case.execute(allow(Budget(usd=3.0, turns=None)))
    assert (declared.was, declared.held) == (
        Budget(usd=2.0, turns=None),
        Budget(usd=3.0, turns=None),
    )
    latest = journal.entries[-1]
    assert (latest.event_type, latest.repo, latest.agent_id) == (
        ALLOWANCE_DECLARED,
        "o/r",
        "safety",
    )
    assert {
        key: latest.payload[key]
        for key in ("per", "usd", "was_usd", "declared_by")
    } == {
        "per": "week",
        "usd": 3.0,
        "was_usd": 2.0,
        "declared_by": "someone@example",
    }
    assert [one.budget for one in bindings.bindings()] == [
        Budget(usd=3.0, turns=None)
    ]


def test_a_declaration_that_changes_nothing_writes_nothing() -> None:
    use_case, _, journal = declaring()
    use_case.execute(allow(Budget(usd=2.0)))
    again = use_case.execute(allow(Budget(usd=2.0)))
    assert not again.changed
    assert len(journal.entries) == 1


def test_revoking_leaves_the_scopes_other_cadences() -> None:
    use_case, bindings, journal = declaring()
    use_case.execute(allow(Budget(usd=2.0)))
    use_case.execute(allow(Budget(usd=0.5), per="event"))
    revoked = use_case.execute(allow(None))
    assert (revoked.was, revoked.held) == (Budget(usd=2.0), None)
    assert journal.entries[-1].payload["held"] is False
    assert [(one.per, one.budget.usd) for one in bindings.bindings()] == [
        ("event", 0.5)
    ]
