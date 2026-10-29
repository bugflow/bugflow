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
    sqlalchemy_archive_facts,
    sqlalchemy_bindings,
    sqlalchemy_block_puts,
    sqlalchemy_kept_events,
    sqlalchemy_search_index,
)
from bugflow.forge.infrastructure import (
    sqlalchemy_forge_facts,
    sqlalchemy_known_repositories,
    sqlalchemy_snapshots,
)
from bugflow.method.infrastructure import (
    sqlalchemy_method_facts,
    sqlalchemy_policy_deployments,
)
from bugflow.review.infrastructure import (
    sqlalchemy_cadence_boundaries,
    sqlalchemy_declaration_facts,
    sqlalchemy_gnome_settings,
    sqlalchemy_judge_archive,
    sqlalchemy_layer_boundaries,
    sqlalchemy_review_facts,
    sqlalchemy_spend_bindings,
    sqlalchemy_stocktake_facts,
    sqlalchemy_withholding,
    sqlalchemy_write_up_archive,
)
from bugflow.shared.infrastructure import (
    sqlalchemy_journal,
    sqlalchemy_repository_associations,
)
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.migrations import VERSION_TABLE, upgrade
from bugflow.work.infrastructure import sqlalchemy_work_facts


def defined() -> sa.MetaData:
    """Every adapter's tables, gathered into one description."""
    together = sa.MetaData()
    for metadata in (
        sqlalchemy_bindings.metadata,
        sqlalchemy_kept_events.metadata,
        sqlalchemy_archive_facts.metadata,
        sqlalchemy_block_puts.metadata,
        sqlalchemy_search_index.metadata,
        sqlalchemy_journal.metadata,
        sqlalchemy_repository_associations.metadata,
        sqlalchemy_snapshots.metadata,
        sqlalchemy_forge_facts.metadata,
        sqlalchemy_known_repositories.metadata,
        sqlalchemy_review_facts.metadata,
        sqlalchemy_stocktake_facts.metadata,
        sqlalchemy_method_facts.metadata,
        sqlalchemy_work_facts.metadata,
        sqlalchemy_judge_archive.metadata,
        sqlalchemy_write_up_archive.metadata,
        sqlalchemy_gnome_settings.metadata,
        sqlalchemy_declaration_facts.metadata,
        sqlalchemy_withholding.metadata,
        sqlalchemy_spend_bindings.metadata,
        sqlalchemy_layer_boundaries.metadata,
        sqlalchemy_cadence_boundaries.metadata,
        sqlalchemy_policy_deployments.metadata,
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
