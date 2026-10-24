"""Tests of the scripts that create and change a database's tables: that a
database records what it has run, that programs starting together do not
collide, and that tables already there are kept.

Skipped unless DATABASE_URL names a Postgres server.
"""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.script.revision import ResolutionError

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.migrations import (
    VERSION_TABLE,
    downgrade,
    pending,
    upgrade,
)
from bugflow.shared.infrastructure.sqlalchemy_journal import (
    journal,
    metadata,
)
from bugflow.shared.tests.postgres import scratch_database
from bugflow.shared.tests.test_the_journal_in_postgres import entry, rows

LAST = "0009"


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


#: A deployment's own script: a branch of the package's that depends on
#: the script that made the journal, since its table refers to an event.
DEPLOYMENT_SCRIPT = """
import sqlalchemy as sa
from alembic import op

revision = "d0001"
down_revision = None
branch_labels = ("deployment",)
depends_on = "0002"


def upgrade() -> None:
    op.create_table(
        "deployment_notes",
        sa.Column("event_id", sa.Text, primary_key=True),
        sa.Column("note", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("deployment_notes")
"""


def test_a_deployments_own_scripts_run_as_a_branch_of_the_packages(
    empty: str, tmp_path: Path
) -> None:
    """The deployment's script runs after the package script it depends
    on, and the one version table records both heads."""
    (tmp_path / "d0001_deployment_notes.py").write_text(DEPLOYMENT_SCRIPT)
    scripts = [str(tmp_path)]

    not_run = pending(empty, scripts)
    assert not_run.index("d0001_deployment_notes") > not_run.index(
        "s0002_the_journal"
    )

    upgrade(empty, scripts)

    assert pending(empty, scripts) == []
    assert set(last_run(empty)) == {LAST, "d0001"}
    engine = sa.create_engine(engine_url(empty))
    try:
        assert sa.inspect(engine).has_table("deployment_notes")
    finally:
        engine.dispose()


def test_a_branch_not_yet_recorded_is_pending_on_an_up_to_date_database(
    empty: str, tmp_path: Path
) -> None:
    """A deployment adds its branch to a database that has run every
    package script, and the branch alone is what remains to run."""
    (tmp_path / "d0001_deployment_notes.py").write_text(DEPLOYMENT_SCRIPT)
    upgrade(empty)

    assert pending(empty, [str(tmp_path)]) == ["d0001_deployment_notes"]


def test_a_database_with_a_branch_is_read_with_the_branchs_scripts(
    empty: str, tmp_path: Path
) -> None:
    """The package's scripts alone do not know the branch's head, and
    say so rather than run anything."""
    (tmp_path / "d0001_deployment_notes.py").write_text(DEPLOYMENT_SCRIPT)
    upgrade(empty, [str(tmp_path)])

    with pytest.raises(ResolutionError, match="d0001"):
        pending(empty)


def tables(database_url: str) -> set[str]:
    engine = sa.create_engine(engine_url(database_url))
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_the_renames_can_be_backed_out_and_run_again(empty: str) -> None:
    """A deployment returns to the previous tag by reversing the script
    that renamed the tables, and moves forward again by running it."""
    upgrade(empty)
    assert {"spend_binding", "repository_association"} <= tables(empty)

    downgrade(empty, "0008")

    assert last_run(empty) == ["0008"]
    assert {"spend_bindings", "repository_associations"} <= tables(empty)
    assert "spend_binding" not in tables(empty)

    upgrade(empty)

    assert last_run(empty) == [LAST]
    assert "spend_bindings" not in tables(empty)
