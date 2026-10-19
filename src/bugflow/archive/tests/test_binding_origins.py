"""A ledger origin persists independently of its hostless reference."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
import sqlalchemy as sa

from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.archive.dtos.bind_ledger import BindLedgerRequest
from bugflow.archive.infrastructure import sqlalchemy_bindings
from bugflow.archive.infrastructure.in_memory_bindings import InMemoryBindings
from bugflow.archive.infrastructure.sqlalchemy_bindings import (
    SqlAlchemyBindings,
)
from bugflow.archive.tests.test_a_ledger_is_bound_by_an_operator import (
    TickingClock,
)
from bugflow.archive.usecases.bind_ledger import BindLedgerUseCase
from bugflow.shared.domain.values.repository_association import (
    AssociationConflictError,
    RepositoryAssociation,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal
from bugflow.shared.infrastructure.in_memory_repository_associations import (
    InMemoryRepositoryAssociations,
)
from bugflow.shared.infrastructure.sqlalchemy_repository_associations import (
    SqlAlchemyRepositoryAssociations,
    associate_on_connection,
)


@pytest.fixture(params=["memory", "postgres"])
def bindings(
    request: pytest.FixtureRequest,
) -> InMemoryBindings | SqlAlchemyBindings:
    if request.param == "memory":
        return InMemoryBindings()
    request.getfixturevalue("engine")
    return SqlAlchemyBindings(request.getfixturevalue("database_url"))


def bound(origin: str | None = "one.example/team/repo") -> ArchiveBinding:
    return ArchiveBinding(
        ledger_id=str(uuid.uuid4()),
        forge="forgejo",
        repo="team/repo",
        origin=origin,
    )


def test_same_path_on_two_hosts_keeps_distinct_origins(
    bindings: InMemoryBindings | SqlAlchemyBindings,
) -> None:
    one, two = bound(), bound("two.example/team/repo")
    for binding in (one, two):
        bindings.save(binding)
        assert bindings.for_ledger(binding.ledger_id) == binding
    assert {
        b.origin
        for b in bindings.bindings()
        if b.ledger_id in (one.ledger_id, two.ledger_id)
    } == {one.origin, two.origin}


@pytest.mark.parametrize("origin", [None, "two.example/team/repo"])
def test_known_binding_cannot_be_downgraded_or_reassigned(
    bindings: InMemoryBindings | SqlAlchemyBindings, origin: str | None
) -> None:
    first = bound()
    bindings.save(first)
    with pytest.raises(AssociationConflictError):
        bindings.save(replace(first, origin=origin, scope="other"))
    assert bindings.for_ledger(first.ledger_id) == first


def test_operator_can_resolve_a_legacy_binding_and_move_its_scope(
    bindings: InMemoryBindings | SqlAlchemyBindings,
) -> None:
    legacy = bound(None)
    bindings.save(legacy)
    known = replace(legacy, origin="one.example/team/repo")
    bindings.save(known)
    moved = replace(known, scope="docs")
    bindings.save(moved)
    assert bindings.for_ledger(legacy.ledger_id) == moved


def test_origin_path_mismatch_leaves_no_binding(
    bindings: InMemoryBindings | SqlAlchemyBindings,
) -> None:
    binding = bound("one.example/team/other")
    with pytest.raises(ValueError, match="does not match"):
        bindings.save(binding)
    assert bindings.for_ledger(binding.ledger_id) is None


def test_registration_only_names_same_origin_neighbors() -> None:
    associations = InMemoryRepositoryAssociations()
    bindings, journal = (
        InMemoryBindings(),
        InMemoryJournal(associations=associations),
    )
    existing = [bound(), bound(None), bound("two.example/team/repo")]
    for binding in existing:
        bindings.save(binding)
    case = BindLedgerUseCase(bindings, journal, TickingClock(), "registration")
    request = BindLedgerRequest(
        ledger_id=str(uuid.uuid4()),
        forge="forgejo",
        repo="team/repo",
        origin=existing[0].origin,
    )
    result = case.execute(request)
    assert result.origin == existing[0].origin
    assert result.beside == (existing[0].ledger_id,)
    assert (
        str(
            associations.origin_for(
                "journal", str(journal.entries[0].event_id)
            )
        )
        == result.origin
    )
    assert not case.execute(request).bound
    assert len(journal.entries) == 1
    with pytest.raises(AssociationConflictError):
        case.execute(request.model_copy(update={"origin": None}))
    assert len(journal.entries) == 1


def test_explicit_historical_mapping_reads_back_without_rewriting_binding(
    engine: sa.Engine, database_url: str
) -> None:
    bindings = SqlAlchemyBindings(database_url)
    legacy = bound(None)
    bindings.save(legacy)
    associations = SqlAlchemyRepositoryAssociations(database_url)
    associations.associate(
        (
            RepositoryAssociation(
                kind="ledger",
                record_id=legacy.ledger_id,
                origin=RepositoryOrigin("one.example/team/repo"),
            ),
        )
    )
    assert bindings.for_ledger(legacy.ledger_id) == replace(
        legacy, origin="one.example/team/repo"
    )
    with pytest.raises(AssociationConflictError):
        bindings.save(legacy)


def test_competing_registrations_keep_one_binding_and_one_origin(
    engine: sa.Engine, database_url: str
) -> None:
    bindings = SqlAlchemyBindings(database_url)
    first = bound()
    second = replace(first, origin="two.example/team/repo", scope="other")

    def save(binding: ArchiveBinding) -> bool:
        try:
            bindings.save(binding)
            return True
        except AssociationConflictError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, (first, second)))
    assert sorted(results) == [False, True]
    winner = first if results[0] else second
    assert bindings.for_ledger(first.ledger_id) == winner
    assert (
        str(
            SqlAlchemyRepositoryAssociations(database_url).origin_for(
                "ledger", first.ledger_id
            )
        )
        == winner.origin
    )


@pytest.mark.parametrize("existing", [False, True])
def test_failed_binding_save_rolls_back_its_origin(
    engine: sa.Engine,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
) -> None:
    bindings = SqlAlchemyBindings(database_url)
    legacy = bound(None)
    if existing:
        bindings.save(legacy)

    def fail_after_association(
        connection: sa.Connection,
        associations: tuple[RepositoryAssociation, ...],
    ) -> None:
        associate_on_connection(connection, associations)
        raise RuntimeError("interrupted binding save")

    monkeypatch.setattr(
        sqlalchemy_bindings, "associate_on_connection", fail_after_association
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        bindings.save(replace(legacy, origin="one.example/team/repo"))
    assert bindings.for_ledger(legacy.ledger_id) == (
        legacy if existing else None
    )
    assert (
        SqlAlchemyRepositoryAssociations(database_url).origin_for(
            "ledger", legacy.ledger_id
        )
        is None
    )
