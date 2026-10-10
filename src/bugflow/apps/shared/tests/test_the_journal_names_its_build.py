"""Each row the stamped journal writes names the build that wrote it,
against the real database.

Skipped unless DATABASE_URL names a Postgres server.
"""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from bugflow.apps.shared.journals import stamped_journal
from bugflow.shared.domain.models.journal_entry import JournalEntry, event_id
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.infrastructure.sqlalchemy_journal import journal

BUILD = "1" * 40


def new_run() -> Correlation:
    return Correlation(workflow_id="test/journal", run_id=str(uuid4()))


def entry(run: Correlation) -> JournalEntry:
    return JournalEntry(
        event_id=event_id(run, "finding.raised", "a"),
        occurred_at=datetime.now(UTC),
        event_type="finding.raised",
        forge="github",
        repo="example-org/widgets",
        pr_number=1,
        commit_sha=None,
        corpus_version="v1",
        workflow_id=run.workflow_id,
        run_id=run.run_id,
        payload={"key": "a"},
    )


def builds(engine: sa.Engine, run: Correlation) -> list[str | None]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                sa.select(journal.c.build).where(
                    journal.c.run_id == run.run_id
                )
            ).scalars()
        )


def test_a_row_names_the_build_its_journal_was_given(
    engine: sa.Engine, database_url: str
) -> None:
    run = new_run()
    stamped_journal(database_url, BUILD).append([entry(run)])
    assert builds(engine, run) == [BUILD]


def test_a_journal_given_no_build_leaves_the_column_empty(
    engine: sa.Engine, database_url: str
) -> None:
    run = new_run()
    stamped_journal(database_url, None).append([entry(run)])
    assert builds(engine, run) == [None]
