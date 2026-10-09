"""Creates the archive's Postgres tables.

Each adapter module defines the table it uses. There are no migration
scripts: a missing table is created directly from its definition. A
migration will be needed the first time a table that already holds data has
to change.
"""

import sqlalchemy as sa

from bugflow.archive.infrastructure import (
    sqlalchemy_bindings,
    sqlalchemy_block_puts,
    sqlalchemy_kept_events,
    sqlalchemy_search_index,
)
from bugflow.shared.infrastructure.database import engine_url

_DEFINED = (
    sqlalchemy_bindings.metadata,
    sqlalchemy_kept_events.metadata,
    sqlalchemy_block_puts.metadata,
    sqlalchemy_search_index.metadata,
)


def create_tables(database_url: str) -> None:
    """Create whichever of the archive's tables the database does not have.
    Existing tables are not altered.
    """
    engine = sa.create_engine(engine_url(database_url))
    try:
        for metadata in _DEFINED:
            metadata.create_all(engine)
    finally:
        engine.dispose()
