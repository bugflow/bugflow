"""Tests of the scripts that create and change a database's tables: that a
database records what it has run, that programs starting together do not
collide, and that tables already there are kept.

Skipped unless DATABASE_URL names a Postgres server.
"""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import pytest
import sqlalchemy as sa

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.migrations import VERSION_TABLE, upgrade
from bugflow.shared.infrastructure.sqlalchemy_journal import (
    journal,
    metadata,
)
from bugflow.shared.tests.postgres import scratch_database
from bugflow.shared.tests.test_the_journal_in_postgres import entry, rows

LAST = "0008"


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
        seed_legacy(engine, made)

        upgrade(empty)

        assert len(rows(engine, made.event_id)) == 1
        assert last_run(empty) == [LAST]
    finally:
        engine.dispose()


def test_columns_that_are_already_there_are_left_alone(empty: str) -> None:
    """A database whose journal was made with every column the adapter
    defines runs the script that adds some of them and loses nothing."""
    engine = sa.create_engine(engine_url(empty))
    try:
        metadata.create_all(engine)
        made = entry("named")
        seed_legacy(engine, made, "example-org/policies")

        upgrade(empty)

        (row,) = rows(engine, made.event_id)
        assert row["policy_repository"] == "example-org/policies"
        assert last_run(empty) == [LAST]
    finally:
        engine.dispose()


def seed_legacy(
    engine: sa.Engine, made: JournalEntry, policy_repository: str | None = None
) -> None:
    # The current writer requires migration 0008. Seed the old table
    # directly to verify that upgrading preserves pre-migration rows.
    values = asdict(made)
    values.pop("origin")
    values.pop("origin_asserted")
    with engine.begin() as connection:
        connection.execute(
            journal.insert().values(
                values | {"policy_repository": policy_repository}
            )
        )
