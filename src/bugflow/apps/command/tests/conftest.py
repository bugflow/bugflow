"""An empty database that has run the scripts, for the tests that run
``install-policies`` against one."""

from collections.abc import Iterator

import pytest

from bugflow.shared.infrastructure.migrations import upgrade
from bugflow.shared.tests.postgres import scratch_database


@pytest.fixture
def database_url() -> Iterator[str]:
    for url in scratch_database():
        upgrade(url)
        yield url
