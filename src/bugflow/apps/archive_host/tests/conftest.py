"""An empty database for the tests that start the host as it is run."""

from collections.abc import Iterator

import pytest

from bugflow.shared.tests.postgres import scratch_database


@pytest.fixture
def database_url() -> Iterator[str]:
    yield from scratch_database()
