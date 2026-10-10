"""Test fixtures: a temporary database that has run the scripts, made
for one test."""

from collections.abc import Iterator

import pytest

from bugflow.shared.infrastructure.migrations import upgrade
from bugflow.shared.tests.postgres import scratch_database


@pytest.fixture
def database_url() -> Iterator[str]:
    """A database with every table and nothing in them. One for each
    test, because which deployment is in force is said once for a whole
    database."""
    for url in scratch_database():
        upgrade(url)
        yield url
