"""The snapshot store, in Postgres.

One row for each snapshot, holding the whole snapshot as JSON. The row's
key is the hash of the snapshot's content, so storing the same content
again changes nothing.

A snapshot can hold people's names. This table may have rows deleted, which
the journal never may.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, insert

from bugflow.forge.domain.errors import SnapshotNotFoundError
from bugflow.forge.domain.models.pull_request import (
    PullRequestSnapshot,
    SnapshotRef,
)
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.serde import from_json, to_json

metadata = sa.MetaData()
snapshots = sa.Table(
    "pull_request_snapshots",
    metadata,
    sa.Column("snapshot_id", sa.Text, primary_key=True),
    sa.Column(
        "stored_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("body", JSONB, nullable=False),
)


class SqlAlchemySnapshotStore:
    """Implements ``SnapshotStoreRepository`` over the
    ``pull_request_snapshots`` table.
    """

    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def put(self, snapshot: PullRequestSnapshot) -> SnapshotRef:
        reference = SnapshotRef(
            snapshot_id=snapshot.content_id, ref=snapshot.ref
        )
        statement = (
            insert(snapshots)
            .values(
                snapshot_id=reference.snapshot_id,
                body=to_json(snapshot),
            )
            .on_conflict_do_nothing(index_elements=["snapshot_id"])
        )
        with self._engine.begin() as connection:
            connection.execute(statement)
        return reference

    def get(self, reference: SnapshotRef) -> PullRequestSnapshot:
        query = sa.select(snapshots.c.body).where(
            snapshots.c.snapshot_id == reference.snapshot_id
        )
        with self._engine.connect() as connection:
            body = connection.execute(query).scalar_one_or_none()
        if body is None:
            raise SnapshotNotFoundError(
                f"no stored snapshot {reference.snapshot_id}"
            )
        return from_json(PullRequestSnapshot, body)
