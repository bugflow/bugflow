"""Tests of the Postgres journal: that it stores entries, that the database
refuses changes to them in any of the five journals, and that the view
and the tables have the columns other software relies on (ADR 006).

Skipped unless DATABASE_URL names a Postgres server.
"""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
import sqlalchemy as sa

from bugflow.shared.domain.models.journal_entry import JournalEntry, fact_id
from bugflow.shared.domain.models.journal_kind import KIND_OF, KINDS
from bugflow.shared.infrastructure.migrations import upgrade
from bugflow.shared.infrastructure.sqlalchemy_journal import (
    SqlAlchemyJournal,
    journal,
)

#: The five tables a fact is written to, one for each kind.
JOURNALS = [f"{kind}_journal" for kind in KINDS]

# The columns other software relies on: name -> (type, nullable)
CONTRACT = {
    "event_id": ("uuid", "NO"),
    "occurred_at": ("timestamp with time zone", "NO"),
    "recorded_at": ("timestamp with time zone", "NO"),
    "event_type": ("text", "NO"),
    "forge": ("text", "NO"),
    "repo": ("text", "NO"),
    "pr_number": ("integer", "YES"),
    "commit_sha": ("text", "YES"),
    "corpus_version": ("text", "YES"),
    "workflow_id": ("text", "NO"),
    "run_id": ("text", "NO"),
    "payload": ("jsonb", "NO"),
}


def entry(key: str, **changed: object) -> JournalEntry:
    made = JournalEntry(
        event_id=fact_id("a-test", key),
        occurred_at=datetime(2026, 10, 1, tzinfo=UTC),
        event_type="archive.sealed",
        forge="a-forge",
        repo="some/one",
        pr_number=None,
        commit_sha=None,
        corpus_version=None,
        workflow_id="a-workflow",
        run_id="a-run",
        payload={"key": key, "nested": {"n": 1}},
    )
    return replace(made, **changed)  # type: ignore[arg-type]


def rows(engine: sa.Engine, event_id: UUID) -> list[sa.RowMapping]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                sa.select(journal).where(journal.c.event_id == event_id)
            ).mappings()
        )


def columns(
    engine: sa.Engine, relation: str = "journal"
) -> dict[str, tuple[str, str, str | None]]:
    query = sa.text(
        "select column_name, data_type, is_nullable, column_default "
        "from information_schema.columns where table_name = :relation"
    )
    with engine.connect() as connection:
        return {
            name: (data_type, nullable, default)
            for name, data_type, nullable, default in connection.execute(
                query, {"relation": relation}
            )
        }


def test_an_entry_is_kept_as_it_was_made(
    engine: sa.Engine, database_url: str
) -> None:
    made = entry("kept", pr_number=7, commit_sha="abc", agent_id="an-agent")
    SqlAlchemyJournal(database_url).append([made])

    (row,) = rows(engine, made.event_id)
    assert row["occurred_at"] == made.occurred_at
    assert row["event_type"] == "archive.sealed"
    assert (row["pr_number"], row["commit_sha"]) == (7, "abc")
    assert row["agent_id"] == "an-agent"
    assert row["payload"] == made.payload
    assert row["recorded_at"] is not None


def test_a_repeated_event_id_is_ignored(
    engine: sa.Engine, database_url: str
) -> None:
    stored = SqlAlchemyJournal(database_url)
    first = entry("twice")
    stored.append([first])
    stored.append([replace(first, payload={"later": True}), entry("other")])

    (row,) = rows(engine, first.event_id)
    assert row["payload"] == first.payload
    assert stored.has_event(entry("other").event_id)
    assert not stored.has_event(fact_id("a-test", "never"))


def test_the_adapter_s_build_is_stamped_and_an_entry_s_is_not_trusted(
    engine: sa.Engine, database_url: str
) -> None:
    made = entry("stamped", build="what-the-producer-said")
    SqlAlchemyJournal(database_url, build="a-build").append([made])

    (row,) = rows(engine, made.event_id)
    assert row["build"] == "a-build"


@pytest.mark.parametrize("table", JOURNALS)
@pytest.mark.parametrize(
    "change",
    [
        "UPDATE {table} SET repo = 'another/one'",
        "DELETE FROM {table}",
        "TRUNCATE {table}",
    ],
)
def test_the_database_refuses_to_change_a_recorded_fact(
    engine: sa.Engine, database_url: str, table: str, change: str
) -> None:
    """A row trigger fires for a row, so each journal holds one first."""
    kind = table.removesuffix("_journal")
    event_type = next(t for t, k in KIND_OF.items() if k == kind)
    made = entry(f"unchanging-{kind}", event_type=event_type)
    SqlAlchemyJournal(database_url).append([made])

    with (
        pytest.raises(sa.exc.DBAPIError, match="append-only"),
        engine.begin() as connection,
    ):
        connection.execute(sa.text(change.format(table=table)))
    assert len(rows(engine, made.event_id)) == 1


def test_running_the_scripts_again_leaves_the_table_as_it_is(
    engine: sa.Engine, database_url: str
) -> None:
    made = entry("survives")
    SqlAlchemyJournal(database_url).append([made])

    upgrade(database_url)

    assert len(rows(engine, made.event_id)) == 1


@pytest.mark.parametrize("table", JOURNALS)
def test_the_append_only_triggers_are_in_place(
    engine: sa.Engine, table: str
) -> None:
    query = sa.text(
        "select tgname from pg_trigger "
        "where tgrelid = cast(:table as regclass) and not tgisinternal"
    )
    with engine.connect() as connection:
        names = {row[0] for row in connection.execute(query, {"table": table})}
    assert names == {f"{table}_append_only", f"{table}_no_truncate"}


@pytest.mark.parametrize("table", JOURNALS)
def test_contract_columns_are_present_and_unchanged(
    engine: sa.Engine, table: str
) -> None:
    actual = columns(engine, table)
    for name, expected in CONTRACT.items():
        assert name in actual, f"{table} lost the {name} column"
        assert actual[name][:2] == expected, f"{table} changed {name}"


def test_the_view_has_the_contract_columns(engine: sa.Engine) -> None:
    """A view carries the types and not the constraints, so the names and
    the types are what it is held to; the tables hold the rest."""
    actual = columns(engine)
    for name, (data_type, _) in CONTRACT.items():
        assert name in actual, f"the journal view lost the {name} column"
        assert actual[name][0] == data_type, f"the journal view changed {name}"


@pytest.mark.parametrize("table", JOURNALS)
def test_added_columns_do_not_break_existing_writers(
    engine: sa.Engine, table: str
) -> None:
    extras = {
        name: shape
        for name, shape in columns(engine, table).items()
        if name not in CONTRACT
    }
    for name, (_, nullable, default) in extras.items():
        assert nullable == "YES" or default is not None, (
            f"{name} is required with no default"
        )
