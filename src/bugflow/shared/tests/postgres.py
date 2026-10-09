"""A temporary Postgres database for tests.

Tests that need Postgres read the server's address from the DATABASE_URL
environment variable. They do not use the database it names. They create a
new one with a random name on the same server and drop it when done, so
they cannot damage real data.
"""

import os
import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy as sa

from bugflow.shared.infrastructure.database import engine_url


def scratch_database() -> Iterator[str]:
    """Create an empty database, yield its URL, and drop it afterwards. If
    DATABASE_URL is not set, the test that asked is skipped.
    """
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
