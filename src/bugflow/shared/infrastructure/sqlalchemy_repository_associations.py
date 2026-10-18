"""Append repository associations atomically; refuse reassignment."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from bugflow.shared.domain.values.repository_association import (
    AssociationConflictError,
    RecordKind,
    RepositoryAssociation,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin
from bugflow.shared.infrastructure.database import engine_url

metadata = sa.MetaData()
repository_associations = sa.Table(
    "repository_associations",
    metadata,
    sa.Column("kind", sa.Text, primary_key=True),
    sa.Column("record_id", sa.Text, primary_key=True),
    sa.Column("origin", sa.Text, nullable=False),
    sa.Column(
        "associated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.CheckConstraint("kind IN ('journal', 'snapshot', 'ledger')"),
    sa.CheckConstraint("record_id <> '' AND origin <> ''"),
)
sa.Index(
    "repository_associations_origin_idx",
    repository_associations.c.origin,
    repository_associations.c.kind,
)


class SqlAlchemyRepositoryAssociations:
    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(engine_url(database_url))

    def close(self) -> None:
        self._engine.dispose()

    def associate(
        self, associations: tuple[RepositoryAssociation, ...]
    ) -> None:
        with self._engine.begin() as connection:
            associate_on_connection(connection, associations)

    def origin_for(
        self, kind: RecordKind, record_id: str
    ) -> RepositoryOrigin | None:
        table = repository_associations
        with self._engine.connect() as connection:
            held = connection.execute(
                sa.select(table.c.origin).where(
                    table.c.kind == kind,
                    table.c.record_id == record_id,
                )
            ).scalar_one_or_none()
        return None if held is None else RepositoryOrigin(held)


def association_exists(
    kind: RecordKind,
    record_id: sa.ColumnElement[str],
    origin: str | None = None,
) -> sa.ColumnElement[bool]:
    table = repository_associations
    predicates = [table.c.kind == kind, table.c.record_id == record_id]
    if origin is not None:
        predicates.append(table.c.origin == origin)
    return sa.exists(sa.select(table.c.record_id).where(*predicates))


def associate_on_connection(
    connection: sa.Connection, associations: tuple[RepositoryAssociation, ...]
) -> None:
    table = repository_associations
    # A stable order avoids deadlocks between overlapping batches.
    for one in sorted(associations, key=lambda a: (a.kind, a.record_id)):
        connection.execute(
            insert(table)
            .values(
                kind=one.kind,
                record_id=one.record_id,
                origin=str(one.origin),
            )
            .on_conflict_do_nothing()
        )
        held = connection.execute(
            sa.select(table.c.origin).where(
                table.c.kind == one.kind,
                table.c.record_id == one.record_id,
            )
        ).scalar_one()
        if held != str(one.origin):
            raise AssociationConflictError(
                "retained record already has another repository origin"
            )
