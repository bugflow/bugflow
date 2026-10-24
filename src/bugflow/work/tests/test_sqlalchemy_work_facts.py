"""A completion is unpacked as it is written: a row of its own beside
the envelope, in the same transaction (ADR 007).

Skipped unless DATABASE_URL names a Postgres server.
"""

from datetime import UTC, datetime

import sqlalchemy as sa

from bugflow.shared.domain.models.journal_entry import JournalEntry, fact_id
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.migrations import upgrade
from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal
from bugflow.work.infrastructure.sqlalchemy_work_facts import (
    UNPACKERS,
    completion,
)


def test_a_completion_is_unpacked(database_url: str) -> None:
    upgrade(database_url)
    received = JournalEntry(
        event_id=fact_id("work-facts-test", "completion", "r-1"),
        occurred_at=datetime(2026, 10, 25, 11, tzinfo=UTC),
        event_type="completion.received",
        forge="github",
        repo="o/r",
        pr_number=7,
        commit_sha=None,
        corpus_version=None,
        workflow_id="review/github/o/r/7",
        run_id="run-1",
        payload={
            "runner": "codex",
            "remote_id": "r-1",
            "outcome": "matched",
            "reason": "a dispatch was waiting for it",
        },
    )
    SqlAlchemyJournal(database_url, unpackers=UNPACKERS).append([received])
    engine = sa.create_engine(engine_url(database_url))
    try:
        with engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(completion).where(
                        completion.c.event_id == received.event_id
                    )
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()
    assert (row["runner"], row["remote_id"], row["outcome"]) == (
        "codex",
        "r-1",
        "matched",
    )
