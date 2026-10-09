"""Test fixtures: a temporary database with the journal table in it."""

from collections.abc import Iterator

import pytest
import sqlalchemy as sa

from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.sqlalchemy_journal import create_tables
from bugflow.shared.tests.postgres import scratch_database


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from scratch_database()


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[sa.Engine]:
    create_tables(database_url)
    engine = sa.create_engine(engine_url(database_url))
    yield engine
    engine.dispose()
