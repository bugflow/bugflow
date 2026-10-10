"""The forge context's questions of the journal, answered from the
journal's Postgres table.

This class only reads. Writing to the journal is done by
``bugflow.shared.infrastructure.sqlalchemy_journal.SqlAlchemyJournal``.
"""

from datetime import datetime

import sqlalchemy as sa

from bugflow.forge.domain import facts
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.serde import from_columns
from bugflow.shared.infrastructure.sqlalchemy_journal import journal

# The columns a ``JournalEntry`` is built from. The table has one more,
# ``recorded_at``, which the database fills in.
_ENTRY = [column for column in journal.c if column.name != "recorded_at"]


class SqlAlchemyJournalQueries:
    """The three queries declared in
    ``forge/domain/services/journal_history.py``."""

    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def events_for_pull_request(
        self, ref: PullRequestRef, event_type: str
    ) -> list[JournalEntry]:
        query = (
            sa.select(*_ENTRY)
            .where(
                journal.c.forge == ref.forge,
                journal.c.repo == f"{ref.owner}/{ref.repo}",
                journal.c.pr_number == ref.number,
                journal.c.event_type == event_type,
            )
            .order_by(journal.c.occurred_at, journal.c.recorded_at)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return [from_columns(JournalEntry, row) for row in rows]

    def repositories_with(self, event_type: str) -> list[tuple[str, str]]:
        query = (
            sa.select(journal.c.forge, journal.c.repo)
            .where(journal.c.event_type == event_type)
            .distinct()
            .order_by(journal.c.forge, journal.c.repo)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).all()
        return [(row.forge, row.repo) for row in rows]

    def received_since(self, ref: PullRequestRef, since: datetime) -> bool:
        query = (
            sa.select(journal.c.event_id)
            .where(
                journal.c.event_type == facts.DELIVERY_RECEIVED,
                journal.c.forge == ref.forge,
                journal.c.repo == f"{ref.owner}/{ref.repo}",
                journal.c.pr_number == ref.number,
                journal.c.occurred_at >= since,
            )
            .limit(1)
        )
        with self._engine.connect() as connection:
            return connection.execute(query).first() is not None
