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
from bugflow.shared.domain.errors import ContentTooLargeError
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.domain.values.repository_association import (
    RepositoryAssociation,
    RepositoryAssociationUnresolvedError,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.serde import from_json, to_json
from bugflow.shared.infrastructure.sqlalchemy_repository_associations import (
    associate_on_connection,
    association_exists,
)

metadata = sa.MetaData()
snapshots = sa.Table(
    "pull_request_snapshot",
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
    ``pull_request_snapshot`` table.
    """

    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def has_contribution(
        self,
        ref: PullRequestRef,
        emails: frozenset[str],
        *,
        origin: str | None = None,
    ) -> bool:
        aliases = sorted(email for email in emails if email.strip())
        if not aliases:
            return False
        # JSON containment matches any commit in any retained snapshot.
        # Only the existence result crosses the database connection.
        matches = [
            snapshots.c.body.contains(
                {
                    "ref": to_json(ref)
                    if origin is None
                    else {
                        "forge": ref.forge,
                        "number": ref.number,
                    },
                    "commits": [{role: {"email": email}}],
                }
            )
            for email in aliases
            for role in ("author", "committer")
        ]
        predicates = [sa.or_(*matches)]
        if origin is not None:
            predicates.append(
                association_exists("snapshot", snapshots.c.snapshot_id, origin)
            )
        query = sa.select(sa.exists().where(*predicates))
        with self._engine.connect() as connection:
            return bool(connection.execute(query).scalar_one())

    def put(self, snapshot: PullRequestSnapshot) -> SnapshotRef:
        reference = SnapshotRef(
            snapshot_id=snapshot.content_id, ref=snapshot.ref
        )
        body = to_json(snapshot)
        if snapshot.origin is None:
            body.pop("origin")
        statement = (
            insert(snapshots)
            .values(
                snapshot_id=reference.snapshot_id,
                body=body,
            )
            .on_conflict_do_nothing(index_elements=["snapshot_id"])
        )
        with self._engine.begin() as connection:
            connection.execute(statement)
            if snapshot.origin is not None:
                associate_on_connection(
                    connection,
                    (
                        RepositoryAssociation(
                            kind="snapshot",
                            record_id=reference.snapshot_id,
                            origin=RepositoryOrigin(snapshot.origin),
                        ),
                    ),
                )
        return reference

    def get(self, reference: SnapshotRef) -> PullRequestSnapshot:
        if reference.origin is not None:
            raise ValueError("canonical snapshots require the bounded reader")
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

    def get_bounded(
        self, reference: SnapshotRef, max_bytes: int
    ) -> tuple[PullRequestSnapshot, int]:
        size = 1024 + sa.func.octet_length(
            sa.func.convert_to(sa.cast(snapshots.c.body, sa.Text), "UTF8")
        )
        allowed = (
            sa.true()
            if reference.origin is None
            else sa.and_(
                association_exists(
                    "snapshot", snapshots.c.snapshot_id, reference.origin
                ),
                snapshots.c.body.contains(
                    {
                        "ref": {
                            "forge": reference.ref.forge,
                            "number": reference.ref.number,
                        }
                    }
                ),
            )
        )
        associated = association_exists("snapshot", snapshots.c.snapshot_id)
        query = sa.select(
            size.label("bytes"),
            allowed.label("allowed"),
            associated.label("associated"),
            sa.case(
                (sa.and_(allowed, size <= max_bytes), snapshots.c.body)
            ).label("body"),
        ).where(snapshots.c.snapshot_id == reference.snapshot_id)
        with self._engine.connect() as connection:
            row = connection.execute(query).one_or_none()
        if row is None:
            raise SnapshotNotFoundError(
                f"no stored snapshot {reference.snapshot_id}"
            )
        if reference.origin is not None and not row.associated:
            raise RepositoryAssociationUnresolvedError(
                "snapshot has no repository association"
            )
        if not row.allowed:
            raise SnapshotNotFoundError("no stored snapshot in this scope")
        if row.bytes > max_bytes:
            raise ContentTooLargeError("snapshot exceeds the byte allowance")
        return from_json(PullRequestSnapshot, row.body), row.bytes
