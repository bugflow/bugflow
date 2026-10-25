"""The stocktake's facts are unpacked as they are written: each has rows
of its own beside the envelope, in the same transaction (ADR 007).

Skipped unless DATABASE_URL names a Postgres server.
"""

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from bugflow.review.infrastructure.sqlalchemy_stocktake_facts import (
    UNPACKERS,
    stocktake,
    stocktake_dispatch,
    stocktake_finding,
    stocktake_grade,
    stocktake_pull_request,
    stocktake_review,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry, fact_id
from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal

AT = datetime(2026, 10, 25, 10, tzinfo=UTC)


def entry(event_type: str, key: str, payload: dict[str, Any]) -> JournalEntry:
    return JournalEntry(
        event_id=fact_id("stocktake-facts-test", event_type, key),
        occurred_at=AT,
        event_type=event_type,
        forge="github",
        repo="o/r",
        pr_number=None,
        commit_sha=None,
        corpus_version=None,
        workflow_id="stocktake/github/o/r/weekly",
        run_id="run-1",
        agent_id=payload.get("agent_id"),
        payload=payload,
    )


def one(engine: sa.Engine, table: sa.Table, event_id: object) -> Any:
    with engine.connect() as connection:
        return (
            connection.execute(
                sa.select(table).where(table.c.event_id == event_id)
            )
            .mappings()
            .one()
        )


def rows(
    engine: sa.Engine, table: sa.Table, event_id: object, *order: str
) -> list[tuple[Any, ...]]:
    with engine.connect() as connection:
        return [
            tuple(r)
            for r in connection.execute(
                sa.select(table)
                .where(table.c.event_id == event_id)
                .order_by(*(table.c[c] for c in order))
            ).all()
        ]


def write(database_url: str, *entries: JournalEntry) -> None:
    SqlAlchemyJournal(database_url, unpackers=UNPACKERS).append(list(entries))


def test_a_stocktake_is_unpacked_with_the_pull_requests_it_covered(
    database_url: str, engine: sa.Engine
) -> None:
    first = entry(
        "stocktake.taken",
        "first",
        {
            "layer": "weekly",
            "since": None,
            "until": "2026-10-18T09:00:00+00:00",
            "merged": 2,
            "pull_requests": [7, 9],
            "base_sha": None,
            "head_sha": "abc",
        },
    )
    empty = entry(
        "stocktake.taken",
        "empty",
        {
            "layer": "weekly",
            "since": "2026-10-18T09:00:00+00:00",
            "until": "2026-10-25T09:00:00+00:00",
            "merged": 0,
            "pull_requests": [],
            "base_sha": "abc",
            "head_sha": None,
        },
    )
    write(database_url, first, empty)
    row = one(engine, stocktake, first.event_id)
    assert (row["since"], row["merged"], row["head_sha"]) == (None, 2, "abc")
    assert row["until"] == datetime(2026, 10, 18, 9, tzinfo=UTC)
    assert [
        r[2]
        for r in rows(
            engine, stocktake_pull_request, first.event_id, "position"
        )
    ] == [7, 9]
    later = one(engine, stocktake, empty.event_id)
    assert (later["since"], later["base_sha"], later["head_sha"]) == (
        datetime(2026, 10, 18, 9, tzinfo=UTC),
        "abc",
        None,
    )
    assert rows(engine, stocktake_pull_request, empty.event_id) == []


def test_a_dispatch_step_is_unpacked_with_its_runner_or_its_reason(
    database_url: str, engine: sa.Engine
) -> None:
    dispatched = entry(
        "stocktake.dispatched",
        "dispatched",
        {
            "layer": "weekly",
            "agent_id": "security",
            "base_sha": "abc",
            "head_sha": "def",
            "step": "dispatched",
            "runner": "managed-agent",
            "remote_id": "r-1",
        },
    )
    refused = entry(
        "stocktake.dispatched",
        "refused",
        {
            "layer": "weekly",
            "agent_id": "security",
            "base_sha": None,
            "head_sha": "def",
            "step": "refused",
            "reason": "the budget is spent",
        },
    )
    write(database_url, dispatched, refused)
    started = one(engine, stocktake_dispatch, dispatched.event_id)
    assert (started["runner"], started["remote_id"], started["reason"]) == (
        "managed-agent",
        "r-1",
        None,
    )
    stopped = one(engine, stocktake_dispatch, refused.event_id)
    assert (stopped["step"], stopped["runner"], stopped["reason"]) == (
        "refused",
        None,
        "the budget is spent",
    )


def test_a_review_a_finding_and_a_grade_are_unpacked(
    database_url: str, engine: sa.Engine
) -> None:
    reviewed = entry(
        "stocktake.reviewed",
        "reviewed",
        {
            "layer": "weekly",
            "agent_id": "security",
            "outcome": "completed",
            "cost": {"usd": 0.31, "seconds": 418.0},
            "detail": "",
            "write_up": "Two findings, one of them a defect.",
        },
    )
    found = entry(
        "stocktake.found",
        "found",
        {
            "layer": "weekly",
            "agent_id": "security",
            "index": 0,
            "where": "src/a.py:12",
            "quote": "token = input()",
            "claim": "the token is read unchecked",
            "kind": "defect",
        },
    )
    graded = entry(
        "stocktake.graded",
        "graded",
        {
            "layer": "weekly",
            "agent_id": "security",
            "status": None,
            "detail": "no verdict",
        },
    )
    write(database_url, reviewed, found, graded)
    review = one(engine, stocktake_review, reviewed.event_id)
    assert (review["cost_usd"], review["cost_seconds"], review["outcome"]) == (
        0.31,
        418.0,
        "completed",
    )
    finding = one(engine, stocktake_finding, found.event_id)
    assert (finding["index"], finding["location"], finding["kind"]) == (
        0,
        "src/a.py:12",
        "defect",
    )
    grade = one(engine, stocktake_grade, graded.event_id)
    assert (grade["status"], grade["detail"]) == (None, "no verdict")
