"""The review context's questions of the journal, answered from the
journal's Postgres table.

This class only reads. Writing to the journal is done by
``bugflow.shared.infrastructure.sqlalchemy_journal.SqlAlchemyJournal``.
"""

import sqlalchemy as sa

from bugflow.review.domain.facts import ACTION_TAKEN
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.serde import from_columns
from bugflow.shared.infrastructure.sqlalchemy_journal import (
    ENTRY_COLUMNS,
    journal,
)


class SqlAlchemyJournalQueries:
    """The four queries declared in
    ``review/domain/services/journal.py``."""

    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def entries_for_run(self, correlation: Correlation) -> list[JournalEntry]:
        return self._entries(
            sa.select(*ENTRY_COLUMNS)
            .where(
                journal.c.workflow_id == correlation.workflow_id,
                journal.c.run_id == correlation.run_id,
            )
            .order_by(journal.c.occurred_at, journal.c.event_type)
        )

    def latest_acted_run(
        self, ref: PullRequestRef, excluding: Correlation
    ) -> Correlation | None:
        query = (
            sa.select(journal.c.workflow_id, journal.c.run_id)
            .where(
                journal.c.forge == ref.forge,
                journal.c.repo == f"{ref.owner}/{ref.repo}",
                journal.c.pr_number == ref.number,
                journal.c.event_type == ACTION_TAKEN,
                sa.not_(
                    sa.and_(
                        journal.c.workflow_id == excluding.workflow_id,
                        journal.c.run_id == excluding.run_id,
                    )
                ),
            )
            .order_by(
                journal.c.occurred_at.desc(), journal.c.recorded_at.desc()
            )
            .limit(1)
        )
        with self._engine.connect() as connection:
            row = connection.execute(query).first()
        if row is None:
            return None
        return Correlation(workflow_id=row.workflow_id, run_id=row.run_id)

    def events_for_pull_request(
        self, ref: PullRequestRef, event_type: str
    ) -> list[JournalEntry]:
        return self._entries(
            sa.select(*ENTRY_COLUMNS)
            .where(
                journal.c.forge == ref.forge,
                journal.c.repo == f"{ref.owner}/{ref.repo}",
                journal.c.pr_number == ref.number,
                journal.c.event_type == event_type,
            )
            .order_by(journal.c.occurred_at, journal.c.recorded_at)
        )

    def events_for_repository(
        self, forge: str, repo: str, event_type: str
    ) -> list[JournalEntry]:
        return self._entries(
            sa.select(*ENTRY_COLUMNS)
            .where(
                journal.c.forge == forge,
                journal.c.repo == repo,
                journal.c.event_type == event_type,
            )
            .order_by(journal.c.occurred_at, journal.c.recorded_at)
        )

    def _entries(
        self, query: sa.Select[tuple[object, ...]]
    ) -> list[JournalEntry]:
        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return [from_columns(JournalEntry, row) for row in rows]
