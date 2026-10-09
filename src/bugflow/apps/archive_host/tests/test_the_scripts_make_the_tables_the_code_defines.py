"""Tests that a database brought up to date by the scripts has the tables
the adapters define: the same tables, columns, types and indexes.

An adapter's table definition and the scripts are written separately, so
a column added to one and not the other would otherwise be found only when
a query failed.

Skipped unless DATABASE_URL names a Postgres server.
"""

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from bugflow.archive.infrastructure import (
    sqlalchemy_bindings,
    sqlalchemy_block_puts,
    sqlalchemy_kept_events,
    sqlalchemy_search_index,
)
from bugflow.forge.infrastructure import sqlalchemy_snapshots
from bugflow.shared.infrastructure import sqlalchemy_journal
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.migrations import VERSION_TABLE, upgrade


def defined() -> sa.MetaData:
    """Every adapter's tables, gathered into one description."""
    together = sa.MetaData()
    for metadata in (
        sqlalchemy_bindings.metadata,
        sqlalchemy_kept_events.metadata,
        sqlalchemy_block_puts.metadata,
        sqlalchemy_search_index.metadata,
        sqlalchemy_journal.metadata,
        sqlalchemy_snapshots.metadata,
    ):
        for table in metadata.tables.values():
            table.to_metadata(together)
    return together


def test_the_scripts_and_the_adapters_agree(database_url: str) -> None:
    upgrade(database_url)
    engine = sa.create_engine(engine_url(database_url))
    try:
        with engine.connect() as connection:
            migrated = MigrationContext.configure(
                connection, opts={"version_table": VERSION_TABLE}
            )
            assert compare_metadata(migrated, defined()) == []
    finally:
        engine.dispose()
