"""Tests of the Postgres snapshot store, against a real database.

Skipped unless DATABASE_URL names a Postgres server.
"""

import uuid

import pytest
import sqlalchemy as sa

from bugflow.forge.domain.errors import SnapshotNotFoundError
from bugflow.forge.domain.models.pull_request import (
    ChangedFile,
    CommitSnapshot,
    PullRequestSnapshot,
    SnapshotRef,
)
from bugflow.forge.infrastructure.sqlalchemy_snapshots import (
    SqlAlchemySnapshotStore,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


def unique_snapshot() -> PullRequestSnapshot:
    return PullRequestSnapshot(
        ref=PullRequestRef(owner="o", repo="r", number=1),
        title=f"Snapshot {uuid.uuid4()}",
        body="A test snapshot.",
        head_branch="test",
        base_branch="master",
        commits=(CommitSnapshot(sha="c" * 40, message="Add a test\n"),),
        files=(
            ChangedFile(path="a.py", additions=2, deletions=1, patch="+a"),
            ChangedFile(path="b.png", additions=0, deletions=0, patch=None),
        ),
    )


def test_a_snapshot_reads_back_as_it_was_stored(
    engine: sa.Engine, database_url: str
) -> None:
    store = SqlAlchemySnapshotStore(database_url)
    original = unique_snapshot()
    assert store.get(store.put(original)) == original


def test_storing_the_same_snapshot_twice_keeps_one_row(
    engine: sa.Engine, database_url: str
) -> None:
    store = SqlAlchemySnapshotStore(database_url)
    original = unique_snapshot()
    store.put(original)
    reference = store.put(original)
    query = sa.text(
        "select count(*) from pull_request_snapshots where snapshot_id = :id"
    )
    with engine.connect() as connection:
        count = connection.execute(query, {"id": reference.snapshot_id})
        assert count.scalar() == 1


def test_a_reference_to_nothing_stored_raises(
    engine: sa.Engine, database_url: str
) -> None:
    store = SqlAlchemySnapshotStore(database_url)
    missing = SnapshotRef(
        snapshot_id="0" * 64, ref=PullRequestRef(owner="o", repo="r", number=1)
    )
    with pytest.raises(SnapshotNotFoundError):
        store.get(missing)
