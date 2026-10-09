"""Test fixtures: a temporary database that has run the scripts."""

from collections.abc import Iterator

import pytest

from bugflow.shared.infrastructure.migrations import upgrade
from bugflow.shared.tests.postgres import scratch_database


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    for url in scratch_database():
        upgrade(url)
        yield url
