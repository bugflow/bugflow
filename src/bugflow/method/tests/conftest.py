"""Test fixtures: a temporary database that has run the scripts."""

from collections.abc import Iterator

import pytest
import sqlalchemy as sa

from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.migrations import upgrade
from bugflow.shared.tests.postgres import scratch_database


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    for url in scratch_database():
        upgrade(url)
        yield url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[sa.Engine]:
    engine = sa.create_engine(engine_url(database_url))
    yield engine
    engine.dispose()
