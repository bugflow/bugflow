"""Tests of registering a ledger.

A ledger is stored only if an operator has registered it. The tests check
what a registration writes to the journal, because a registration that left
no record would let someone replace an archive without anyone noticing.
"""

from datetime import UTC, datetime, timedelta

import pytest

from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.archive.dtos.bind_ledger import BindLedgerRequest, BoundTo
from bugflow.archive.infrastructure.in_memory_bindings import InMemoryBindings
from bugflow.archive.usecases.bind_ledger import BindLedgerUseCase
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal

LEDGER = "0f1e2d3c-4b5a-4968-8778-a6b5c4d3e2f1"
OTHER = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


class TickingClock:
    """A clock that gives a later time on each call, as a real clock does.
    Registering the same ledger twice then gives two different journal
    entries.
    """

    def __init__(self) -> None:
        self._now = datetime(2026, 10, 1, tzinfo=UTC)

    def now(self) -> datetime:
        self._now += timedelta(seconds=1)
        return self._now


def use_case() -> tuple[BindLedgerUseCase, InMemoryBindings, InMemoryJournal]:
    bindings, journal = InMemoryBindings(), InMemoryJournal()
    return (
        BindLedgerUseCase(bindings, journal, TickingClock(), "run"),
        bindings,
        journal,
    )


def request(
    ledger: str = LEDGER, repo: str = "someone/garden", scope: str = ""
) -> BindLedgerRequest:
    return BindLedgerRequest(
        ledger_id=ledger, forge="github", repo=repo, scope=scope
    )


def test_a_ledger_nobody_bound_is_kept_for_no_one() -> None:
    _, bindings, _ = use_case()
    assert bindings.for_ledger(LEDGER) is None


def test_binding_a_ledger_is_a_fact_in_the_journal() -> None:
    bind, bindings, journal = use_case()

    response = bind.execute(request(scope="projects/example"))

    assert response.bound and response.replaces is None
    assert bindings.for_ledger(LEDGER) == ArchiveBinding(
        ledger_id=LEDGER,
        forge="github",
        repo="someone/garden",
        scope="projects/example",
    )
    (fact,) = journal.entries
    assert (fact.event_type, fact.forge, fact.repo) == (
        "archive.bound",
        "github",
        "someone/garden",
    )
    assert fact.payload == {
        "ledger_id": LEDGER,
        "scope": "projects/example",
        "replaces": None,
        "beside": [],
    }


def test_binding_what_is_already_bound_records_nothing() -> None:
    bind, _, journal = use_case()
    bind.execute(request())

    again = bind.execute(request())

    assert not again.bound
    assert len(journal.entries) == 1


def test_moving_a_ledger_says_where_it_was() -> None:
    """When a ledger is registered for a different repository, as after a
    rename, the journal entry records what it was registered for before.
    """
    bind, bindings, journal = use_case()
    bind.execute(request(repo="someone/garden"))

    moved = bind.execute(request(repo="someone/renamed"))

    was = BoundTo(forge="github", repo="someone/garden", scope="")
    assert moved.bound and moved.replaces == was
    assert journal.entries[-1].payload["replaces"] == was.model_dump()
    assert [b.repo for b in bindings.bindings()] == ["someone/renamed"]


def test_a_ledger_moved_away_and_back_is_three_facts() -> None:
    bind, _, journal = use_case()
    for repo in ("someone/garden", "someone/renamed", "someone/garden"):
        bind.execute(request(repo=repo))

    assert len({fact.event_id for fact in journal.entries}) == 3


def test_a_second_ledger_on_a_scope_is_named_beside_the_first() -> None:
    """Registering a second ledger for a scope that already has one is
    allowed. It may be legitimate (a ledger started afresh) or an archive
    being replaced, so both the answer and the journal entry name the
    ledger that was already there.
    """
    bind, bindings, journal = use_case()
    bind.execute(request(LEDGER, scope="projects/example"))

    second = bind.execute(request(OTHER, scope="projects/example"))

    assert second.bound and second.beside == (LEDGER,)
    assert journal.entries[-1].payload["beside"] == [LEDGER]
    assert len(bindings.bindings()) == 2


@pytest.mark.parametrize(
    "ledger,scope",
    [
        ("not-a-uuid", ""),
        (LEDGER.upper(), ""),
        (LEDGER, "/absolute"),
        (LEDGER, "projects/../elsewhere"),
        (LEDGER, "projects//example"),
        (LEDGER, "trailing/"),
    ],
)
def test_what_is_no_ledger_or_no_scope_is_refused_and_not_recorded(
    ledger: str, scope: str
) -> None:
    bind, bindings, journal = use_case()

    with pytest.raises(ValueError):
        bind.execute(request(ledger, scope=scope))

    assert bindings.bindings() == [] and journal.entries == []
