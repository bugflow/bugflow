from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from bugflow.shared.domain.repositories.repository_associations import (
    RepositoryAssociations,
)
from bugflow.shared.domain.values.repository_association import (
    AssociationConflictError,
    RepositoryAssociation,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin
from bugflow.shared.infrastructure.in_memory_repository_associations import (
    InMemoryRepositoryAssociations,
)
from bugflow.shared.infrastructure.migrations import upgrade
from bugflow.shared.infrastructure.sqlalchemy_repository_associations import (
    SqlAlchemyRepositoryAssociations,
)


@pytest.fixture(params=["memory", "postgres"])
def store(request: pytest.FixtureRequest) -> Iterator[RepositoryAssociations]:
    if request.param == "memory":
        yield InMemoryRepositoryAssociations()
    else:
        url = request.getfixturevalue("database_url")
        upgrade(url)
        adapter = SqlAlchemyRepositoryAssociations(url)
        yield adapter
        adapter.close()


def association(
    record_id: str, host: str = "one.example"
) -> RepositoryAssociation:
    return RepositoryAssociation(
        kind="snapshot",
        record_id=record_id,
        origin=RepositoryOrigin.parse(f"{host}/a/b"),
    )


def test_unresolved_records_are_not_assigned_a_default_host(
    store: RepositoryAssociations,
) -> None:
    assert store.origin_for("snapshot", str(uuid4())) is None


def test_same_path_on_two_hosts_never_combines_records(
    store: RepositoryAssociations,
) -> None:
    first, second = (
        association(str(uuid4())),
        association(str(uuid4()), "two.example"),
    )
    store.associate((first, second, first))
    assert store.origin_for("snapshot", first.record_id) == first.origin
    assert store.origin_for("snapshot", second.record_id) == second.origin
    assert first.origin != second.origin
    assert store.origin_for("ledger", first.record_id) is None


def test_a_conflict_rolls_back_the_entire_batch(
    store: RepositoryAssociations,
) -> None:
    held, new = association(str(uuid4())), association(str(uuid4()))
    store.associate((held,))
    with pytest.raises(AssociationConflictError):
        store.associate((new, association(held.record_id, "two.example")))
    assert store.origin_for("snapshot", new.record_id) is None
    assert store.origin_for("snapshot", held.record_id) == held.origin


def test_conflicting_entries_in_one_batch_leave_nothing(
    store: RepositoryAssociations,
) -> None:
    one = association(str(uuid4()))
    with pytest.raises(AssociationConflictError):
        store.associate((one, association(one.record_id, "two.example")))
    assert store.origin_for("snapshot", one.record_id) is None


def test_concurrent_mappings_cannot_replace_an_origin(
    database_url: str,
) -> None:
    upgrade(database_url)
    record_id = str(uuid4())

    def put(host: str) -> bool:
        adapter = SqlAlchemyRepositoryAssociations(database_url)
        try:
            adapter.associate((association(record_id, host),))
            return True
        except AssociationConflictError:
            return False
        finally:
            adapter.close()

    with ThreadPoolExecutor(max_workers=2) as threads:
        assert sorted(threads.map(put, ("one.example", "two.example"))) == [
            False,
            True,
        ]


def test_a_rename_cannot_reinterpret_an_existing_association(
    store: RepositoryAssociations,
) -> None:
    old = association(str(uuid4()))
    renamed = RepositoryAssociation(
        kind=old.kind,
        record_id=old.record_id,
        origin=RepositoryOrigin.parse("one.example/a/renamed"),
    )
    store.associate((old,))
    assert renamed.origin != old.origin
    with pytest.raises(AssociationConflictError):
        store.associate((renamed,))
    assert store.origin_for(old.kind, old.record_id) == old.origin
