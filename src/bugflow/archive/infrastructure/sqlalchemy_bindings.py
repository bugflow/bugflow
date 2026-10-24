"""The store of bindings, in Postgres.

One row for each registered ledger. A ledger with no row is not stored by
this server.

This table holds the current state. The journal separately records each
time a ledger was registered.
"""

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from bugflow.archive.domain.models.binding import (
    ArchiveBinding,
    check_binding_origin,
)
from bugflow.shared.domain.values.repository_association import (
    RepositoryAssociation,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.sqlalchemy_repository_associations import (
    associate_on_connection,
    repository_associations,
)

metadata = sa.MetaData()

archive_bindings = sa.Table(
    "archive_binding",
    metadata,
    sa.Column("ledger_id", sa.Text, primary_key=True),
    sa.Column("forge", sa.Text, nullable=False),
    sa.Column("repo", sa.Text, nullable=False),
    sa.Column("scope", sa.Text, nullable=False),
    sa.Column(
        "declared_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)


def _binding(row: sa.RowMapping) -> ArchiveBinding:
    return ArchiveBinding(
        ledger_id=row["ledger_id"],
        forge=row["forge"],
        repo=row["repo"],
        scope=row["scope"],
        origin=row["origin"],
    )


def _query() -> sa.Select[Any]:
    associations = repository_associations
    return sa.select(archive_bindings, associations.c.origin).select_from(
        archive_bindings.outerjoin(
            associations,
            sa.and_(
                associations.c.kind == "ledger",
                associations.c.record_id == archive_bindings.c.ledger_id,
            ),
        )
    )


class SqlAlchemyBindings:
    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def for_ledger(self, ledger_id: str) -> ArchiveBinding | None:
        query = _query().where(archive_bindings.c.ledger_id == ledger_id)
        with self._engine.connect() as connection:
            row = connection.execute(query).mappings().first()
        return _binding(row) if row else None

    def bindings(self) -> list[ArchiveBinding]:
        query = _query().order_by(
            archive_bindings.c.forge,
            archive_bindings.c.repo,
            archive_bindings.c.scope,
            archive_bindings.c.ledger_id,
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return [_binding(row) for row in rows]

    def save(self, binding: ArchiveBinding) -> None:
        statement = (
            insert(archive_bindings)
            .values(
                ledger_id=binding.ledger_id,
                forge=binding.forge,
                repo=binding.repo,
                scope=binding.scope,
            )
            .on_conflict_do_update(
                index_elements=["ledger_id"],
                set_={
                    "forge": binding.forge,
                    "repo": binding.repo,
                    "scope": binding.scope,
                    "declared_at": sa.func.now(),
                },
            )
        )
        with self._engine.begin() as connection:
            # Serialize binding saves, including competing first registrations.
            connection.execute(
                sa.text(
                    "SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"
                ),
                {"key": "archive-binding/" + binding.ledger_id},
            )
            held = connection.execute(
                sa.select(repository_associations.c.origin).where(
                    repository_associations.c.kind == "ledger",
                    repository_associations.c.record_id == binding.ledger_id,
                )
            ).scalar_one_or_none()
            check_binding_origin(binding, held)
            if binding.origin is not None:
                associate_on_connection(
                    connection,
                    (
                        RepositoryAssociation(
                            kind="ledger",
                            record_id=binding.ledger_id,
                            origin=RepositoryOrigin(binding.origin),
                        ),
                    ),
                )
            connection.execute(statement)
