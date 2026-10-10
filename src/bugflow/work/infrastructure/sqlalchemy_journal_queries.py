"""The work context's questions of the journal, answered from the
journal's Postgres table.

This class only reads. Writing to the journal is done by
``bugflow.shared.infrastructure.sqlalchemy_journal.SqlAlchemyJournal``.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.serde import from_columns
from bugflow.shared.infrastructure.sqlalchemy_journal import (
    ENTRY_COLUMNS,
    journal,
)
from bugflow.work.domain.facts import AGENT_DISPATCHED
from bugflow.work.domain.models.journal import (
    DispatchedRun,
    DispatchedWork,
    dispatched_from_entry,
)


class SqlAlchemyJournalQueries:
    def __init__(
        self,
        database_url: str,
        dispatch_facts: Sequence[str] = (AGENT_DISPATCHED,),
    ) -> None:
        """``dispatch_facts`` names the kinds of fact that
        ``dispatched_run`` searches. A program that also dispatches
        work under a fact of its own names that fact here, so that a
        completion for such work is matched to its workflow run."""
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )
        self._dispatch_facts = tuple(dispatch_facts)

    def events_for_pull_request(
        self, ref: PullRequestRef, event_type: str
    ) -> list[JournalEntry]:
        query = (
            sa.select(*ENTRY_COLUMNS)
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

    def dispatched_run(
        self, runner: str, remote_id: str
    ) -> DispatchedRun | None:
        query = (
            sa.select(
                journal.c.workflow_id,
                journal.c.run_id,
                journal.c.payload["agent_id"].astext.label("agent_id"),
                journal.c.forge,
                journal.c.repo,
                journal.c.pr_number,
                journal.c.commit_sha,
            )
            .where(
                journal.c.event_type.in_(self._dispatch_facts),
                journal.c.payload["step"].astext == "dispatched",
                journal.c.payload["runner"].astext == runner,
                journal.c.payload["remote_id"].astext == remote_id,
            )
            .limit(1)
        )
        with self._engine.connect() as connection:
            row = connection.execute(query).first()
        if row is None:
            return None
        return DispatchedRun(
            correlation=Correlation(
                workflow_id=row.workflow_id, run_id=row.run_id
            ),
            agent_id=row.agent_id or "",
            forge=row.forge or "",
            repo=row.repo or "",
            pr_number=row.pr_number,
            commit_sha=row.commit_sha,
        )

    def dispatched_work(self) -> list[DispatchedWork]:
        query = (
            sa.select(*ENTRY_COLUMNS)
            .where(
                journal.c.event_type == AGENT_DISPATCHED,
                journal.c.payload["step"].astext == "dispatched",
            )
            .order_by(journal.c.occurred_at, journal.c.recorded_at)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return [
            dispatched_from_entry(from_columns(JournalEntry, row))
            for row in rows
        ]
