"""The archive's tables in Postgres, created from their definitions.

Each adapter defines the table it reads and writes. There are no
migrations: a table is created as it is defined, and one is written the
first time a table that holds rows has to change.
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
    """Create each of the archive's tables that the database lacks. One
    already there is left as it is."""
    engine = sa.create_engine(engine_url(database_url))
    try:
        for metadata in _DEFINED:
            metadata.create_all(engine)
    finally:
        engine.dispose()
