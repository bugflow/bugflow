"""The ledgers whose archives this server keeps, against the real
database.

Skipped unless DATABASE_URL names a Postgres. The in-memory double
answers the same questions in the unit test of the use case.
"""

import uuid

import sqlalchemy as sa

from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.archive.infrastructure.sqlalchemy_bindings import (
    SqlAlchemyBindings,
)


def repo() -> str:
    return f"test/{uuid.uuid4()}"


def binding(name: str, scope: str = "") -> ArchiveBinding:
    return ArchiveBinding(
        ledger_id=str(uuid.uuid4()), forge="github", repo=name, scope=scope
    )


def test_a_binding_reads_back_for_its_ledger(
    engine: sa.Engine, database_url: str
) -> None:
    bindings = SqlAlchemyBindings(database_url)
    bound = binding(repo(), "projects/example")
    bindings.save(bound)

    assert bindings.for_ledger(bound.ledger_id) == bound
    assert bindings.for_ledger(str(uuid.uuid4())) is None


def test_binding_a_ledger_again_moves_it(
    engine: sa.Engine, database_url: str
) -> None:
    bindings = SqlAlchemyBindings(database_url)
    first = binding(repo())
    bindings.save(first)
    moved = ArchiveBinding(
        ledger_id=first.ledger_id, forge="github", repo=repo(), scope="x"
    )
    bindings.save(moved)

    assert bindings.for_ledger(first.ledger_id) == moved
    held = [b for b in bindings.bindings() if b.ledger_id == first.ledger_id]
    assert held == [moved]


def test_two_ledgers_may_be_bound_to_one_scope(
    engine: sa.Engine, database_url: str
) -> None:
    bindings = SqlAlchemyBindings(database_url)
    name = repo()
    one, two = binding(name, "s"), binding(name, "s")
    bindings.save(one)
    bindings.save(two)

    ours = [b for b in bindings.bindings() if b.repo == name]
    assert sorted(ours, key=lambda b: b.ledger_id) == sorted(
        [one, two], key=lambda b: b.ledger_id
    )
