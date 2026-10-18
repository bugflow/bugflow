"""Snapshot reads charge their stored content against the allowance."""

from dataclasses import replace
from typing import Any

import pytest
import sqlalchemy as sa

from bugflow.forge.domain.errors import SnapshotNotFoundError
from bugflow.forge.domain.models.pull_request import (
    PullRequestSnapshot,
    SnapshotRef,
)
from bugflow.forge.infrastructure.in_memory_snapshots import (
    InMemorySnapshotStore,
)
from bugflow.forge.infrastructure.sqlalchemy_snapshots import (
    SqlAlchemySnapshotStore,
)
from bugflow.shared.domain.errors import ContentTooLargeError
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.domain.values.repository_association import (
    RepositoryAssociation,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin
from bugflow.shared.infrastructure.sqlalchemy_repository_associations import (
    SqlAlchemyRepositoryAssociations,
)


@pytest.fixture(params=["memory", "postgres"])
def store(
    request: pytest.FixtureRequest,
) -> InMemorySnapshotStore | SqlAlchemySnapshotStore:
    if request.param == "memory":
        return InMemorySnapshotStore()
    request.getfixturevalue("engine")
    return SqlAlchemySnapshotStore(request.getfixturevalue("database_url"))


def test_snapshot_reads_charge_bytes_before_returning_content(
    store: InMemorySnapshotStore | SqlAlchemySnapshotStore,
) -> None:
    snapshot = PullRequestSnapshot(
        ref=PullRequestRef(owner="owner", repo="repo", number=1),
        title="Title",
        body="é漢" * 400,
        head_branch="change",
        base_branch="main",
        commits=(),
        files=(),
    )
    reference = store.put(snapshot)
    found, size = store.get_bounded(reference, 100_000)
    assert found == snapshot
    assert size > len(snapshot.body)
    assert store.get_bounded(reference, size) == (found, size)
    with pytest.raises(ContentTooLargeError):
        store.get_bounded(reference, size - 1)
    assert store.get(reference) == snapshot


def test_a_missing_snapshot_is_not_reported_as_oversized(
    store: InMemorySnapshotStore | SqlAlchemySnapshotStore,
) -> None:
    reference = SnapshotRef(
        snapshot_id="gone", ref=PullRequestRef(owner="o", repo="r", number=1)
    )
    with pytest.raises(SnapshotNotFoundError):
        store.get_bounded(reference, 0)


def test_postgres_suppresses_snapshot_content_before_transfer(
    database_url: str, engine: sa.Engine
) -> None:
    store = SqlAlchemySnapshotStore(database_url)
    reference = store.put(
        PullRequestSnapshot(
            ref=PullRequestRef(owner="owner", repo="repo", number=1),
            title="Title",
            body="é漢" * 10000,
            head_branch="change",
            base_branch="main",
            commits=(),
            files=(),
        )
    )
    queries: list[tuple[str, Any]] = []

    def recorded(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        queries.append((statement, parameters))

    sa.event.listen(store._engine, "after_cursor_execute", recorded)
    try:
        with pytest.raises(ContentTooLargeError):
            store.get_bounded(reference, 4096)
    finally:
        sa.event.remove(store._engine, "after_cursor_execute", recorded)
    assert len(queries) == 1
    # Inspect the result of the exact query issued by the adapter.
    statement, parameters = queries[0]
    with engine.connect() as connection:
        row = connection.exec_driver_sql(statement, parameters).one()
    assert row.bytes > 4096
    assert row.body is None


def test_postgres_suppresses_content_from_another_origin(
    database_url: str, engine: sa.Engine
) -> None:
    store = SqlAlchemySnapshotStore(database_url)
    reference = store.put(
        PullRequestSnapshot(
            ref=PullRequestRef(owner="owner", repo="repo", number=1),
            title="Private",
            body="private evidence",
            head_branch="topic",
            base_branch="main",
            commits=(),
            files=(),
        )
    )
    associations = SqlAlchemyRepositoryAssociations(database_url)
    try:
        associations.associate(
            (
                RepositoryAssociation(
                    kind="snapshot",
                    record_id=reference.snapshot_id,
                    origin=RepositoryOrigin("one.example/owner/repo"),
                ),
            )
        )
    finally:
        associations.close()
    queries: list[tuple[str, Any]] = []

    def recorded(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        queries.append((statement, parameters))

    sa.event.listen(store._engine, "after_cursor_execute", recorded)
    try:
        with pytest.raises(SnapshotNotFoundError):
            store.get_bounded(
                replace(reference, origin="two.example/owner/repo"), 100_000
            )
    finally:
        sa.event.remove(store._engine, "after_cursor_execute", recorded)
    assert len(queries) == 1
    statement, parameters = queries[0]
    with engine.connect() as connection:
        row = connection.exec_driver_sql(statement, parameters).one()
    assert row.body is None
    assert not row.allowed


def test_unbounded_readers_do_not_ignore_a_canonical_selector(
    store: InMemorySnapshotStore | SqlAlchemySnapshotStore,
) -> None:
    reference = SnapshotRef(
        snapshot_id="any",
        ref=PullRequestRef(owner="o", repo="r", number=1),
        origin="one.example/o/r",
    )
    with pytest.raises(ValueError, match="bounded"):
        store.get(reference)
