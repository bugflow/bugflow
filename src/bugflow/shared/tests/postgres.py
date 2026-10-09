"""A database of a test session's own.

DATABASE_URL names a Postgres server. A session makes a database beside
the one it names and drops it afterwards, so tests leave nothing behind
and never touch a database somebody keeps.
"""

import os
import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy as sa

from bugflow.shared.infrastructure.database import engine_url


def scratch_database() -> Iterator[str]:
    """The url of a new, empty database, dropped when the caller is done.
    Skips the test asking when DATABASE_URL names no server."""
    named = os.environ.get("DATABASE_URL")
    if not named:
        pytest.skip("DATABASE_URL names no Postgres to make a database in")
    url = sa.make_url(engine_url(named))
    scratch = f"{url.database}_test_{uuid.uuid4().hex[:8]}"
    server = sa.create_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    with server.connect() as connection:
        connection.execute(sa.text(f'CREATE DATABASE "{scratch}"'))
    try:
        yield url.set(database=scratch).render_as_string(hide_password=False)
    finally:
        with server.connect() as connection:
            connection.execute(
                sa.text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
            )
        server.dispose()
