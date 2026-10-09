"""The ledgers whose archives this server keeps, in the domain Postgres.

Operational storage, not the journal: the journal holds the fact that a
binding was made, and this holds what is bound now. One row per ledger;
a ledger with no row is kept for no one. The table is created from its
definition here.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.shared.infrastructure.database import engine_url

metadata = sa.MetaData()

archive_bindings = sa.Table(
    "archive_bindings",
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
    )


class SqlAlchemyBindings:
    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def for_ledger(self, ledger_id: str) -> ArchiveBinding | None:
        query = sa.select(archive_bindings).where(
            archive_bindings.c.ledger_id == ledger_id
        )
        with self._engine.connect() as connection:
            row = connection.execute(query).mappings().first()
        return _binding(row) if row else None

    def bindings(self) -> list[ArchiveBinding]:
        query = sa.select(archive_bindings).order_by(
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
            connection.execute(statement)
