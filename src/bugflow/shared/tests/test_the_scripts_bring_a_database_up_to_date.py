"""Tests of the scripts that create and change a database's tables: that a
database records what it has run, that programs starting together do not
collide, and that tables already there are kept.

Skipped unless DATABASE_URL names a Postgres server.
"""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa

from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.migrations import VERSION_TABLE, upgrade
from bugflow.shared.infrastructure.sqlalchemy_journal import (
    SqlAlchemyJournal,
    metadata,
)
from bugflow.shared.tests.postgres import scratch_database
from bugflow.shared.tests.test_the_journal_in_postgres import entry, rows

LAST = "0003"


@pytest.fixture
def empty() -> Iterator[str]:
    yield from scratch_database()


def last_run(database_url: str) -> list[str]:
    engine = sa.create_engine(engine_url(database_url))
    try:
        with engine.connect() as connection:
            return [
                row[0]
                for row in connection.execute(
                    sa.text(f"select version_num from {VERSION_TABLE}")
                )
            ]
    finally:
        engine.dispose()


def test_a_database_records_the_last_script_it_ran(empty: str) -> None:
    upgrade(empty)
    assert last_run(empty) == [LAST]

    upgrade(empty)
    assert last_run(empty) == [LAST]


def test_programs_that_start_together_do_not_collide(empty: str) -> None:
    with ThreadPoolExecutor(max_workers=4) as together:
        for done in [together.submit(upgrade, empty) for _ in range(4)]:
            done.result()
    assert last_run(empty) == [LAST]


def test_a_table_that_is_already_there_keeps_its_rows(empty: str) -> None:
    engine = sa.create_engine(engine_url(empty))
    try:
        metadata.create_all(engine)
        made = entry("already-here")
        SqlAlchemyJournal(empty).append([made])

        upgrade(empty)

        assert len(rows(engine, made.event_id)) == 1
        assert last_run(empty) == [LAST]
    finally:
        engine.dispose()
