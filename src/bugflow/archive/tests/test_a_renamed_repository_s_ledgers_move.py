"""Tests of moving the ledgers bound to a renamed repository to its new
name.

A ledger whose origin is unresolved moves, at its scope, and the move is
recorded as an operator's registration is. A ledger with an origin stays,
since its origin names the old name and is never changed.
"""

from bugflow.archive.domain import facts
from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.archive.dtos.move_ledgers import MoveLedgersRequest
from bugflow.archive.infrastructure.in_memory_bindings import InMemoryBindings
from bugflow.archive.tests.test_a_ledger_is_bound_by_an_operator import (
    LEDGER,
    OTHER,
    TickingClock,
)
from bugflow.archive.usecases.bind_ledger import BindLedgerUseCase
from bugflow.archive.usecases.move_ledgers import MoveLedgersUseCase
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal

THIRD = "2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e"
MOVE = MoveLedgersRequest(forge="github", repo="o/old", to="o/new")


def moving(
    *held: ArchiveBinding,
) -> tuple[MoveLedgersUseCase, InMemoryBindings, InMemoryJournal]:
    bindings, journal = InMemoryBindings(), InMemoryJournal()
    for one in held:
        bindings.save(one)
    binder = BindLedgerUseCase(bindings, journal, TickingClock(), "run")
    return MoveLedgersUseCase(bindings, binder), bindings, journal


def bound(
    ledger: str,
    repo: str = "o/old",
    scope: str = "",
    origin: str | None = None,
) -> ArchiveBinding:
    return ArchiveBinding(
        ledger_id=ledger, forge="github", repo=repo, scope=scope, origin=origin
    )


def test_an_unresolved_ledger_moves_at_its_scope() -> None:
    mover, bindings, journal = moving(
        bound(LEDGER), bound(OTHER, scope="published")
    )

    moved = mover.execute(MOVE)

    assert set(moved.moved) == {LEDGER, OTHER}
    assert moved.stayed == ()
    assert bindings.for_ledger(LEDGER) == bound(LEDGER, repo="o/new")
    assert bindings.for_ledger(OTHER) == bound(
        OTHER, repo="o/new", scope="published"
    )
    assert [entry.event_type for entry in journal.entries] == [facts.BOUND] * 2
    assert {entry.repo for entry in journal.entries} == {"o/new"}
    assert {
        entry.payload["replaces"]["repo"] for entry in journal.entries
    } == {"o/old"}


def test_a_ledger_with_an_origin_stays() -> None:
    held = bound(LEDGER, origin="github.com/o/old")
    mover, bindings, journal = moving(held)

    moved = mover.execute(MOVE)

    assert (moved.moved, moved.stayed) == ((), (LEDGER,))
    assert bindings.for_ledger(LEDGER) == held
    assert journal.entries == []


def test_another_repository_s_ledger_is_not_moved() -> None:
    held = bound(THIRD, repo="o/other")
    mover, bindings, _ = moving(held)

    assert mover.execute(MOVE).moved == ()
    assert bindings.for_ledger(THIRD) == held
