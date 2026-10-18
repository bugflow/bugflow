"""Snapshot reads charge their stored content against the allowance."""

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
