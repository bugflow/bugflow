"""A database of the archive's own for the tests that need one.

The adapters over Postgres are run against Postgres. DATABASE_URL names
a server; each session makes a database beside the one it names, creates
the archive's tables there, and drops it afterwards. Without
DATABASE_URL those tests are skipped and say so.
"""

import os
import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy as sa

from bugflow.archive.infrastructure.schema import create_tables
from bugflow.shared.infrastructure.database import engine_url


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
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


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[sa.Engine]:
    create_tables(database_url)
    engine = sa.create_engine(engine_url(database_url))
    yield engine
    engine.dispose()
