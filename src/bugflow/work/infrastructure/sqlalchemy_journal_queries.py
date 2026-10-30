"""The work context's questions of the journal, answered from the
journal's Postgres table.

A dispatch and a judgement are read from their own tables joined to the
view by the event's id (ADR 007): the review journal's envelope carries
no payload. The tables are named here with the columns this context
reads; the review context defines them.

This class only reads. Writing to the journal is done by
``bugflow.shared.infrastructure.sqlalchemy_journal.SqlAlchemyJournal``.
"""

from collections.abc import Mapping

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.serde import from_columns
from bugflow.shared.infrastructure.sqlalchemy_journal import (
    ENTRY_COLUMNS,
    journal,
)
from bugflow.work.domain.facts import AGENT_DISPATCHED, JUDGE_INVOKED
from bugflow.work.domain.models.journal import (
    DispatchedRun,
)

#: The table a review's dispatch is read from.
AGENT_DISPATCH = "agent_dispatch"


def _dispatch_table(name: str) -> sa.TableClause:
    """A dispatch table, named with the columns a dispatch is read by."""
    return sa.table(
        name,
        sa.column("event_id", PG_UUID(as_uuid=True)),
        sa.column("agent_id", sa.Text),
        sa.column("step", sa.Text),
        sa.column("runner", sa.Text),
        sa.column("fingerprint", sa.Text),
        sa.column("remote_id", sa.Text),
        sa.column("budget_usd", sa.Float),
        sa.column("budget_turns", sa.Float),
    )


judge_invocation = sa.table(
    "judge_invocation",
    sa.column("event_id", PG_UUID(as_uuid=True)),
    sa.column("status", sa.Text),
)


class SqlAlchemyJournalQueries:
    def __init__(
        self,
        database_url: str,
        dispatch_tables: Mapping[str, str] | None = None,
    ) -> None:
        """``dispatch_tables`` names, by the kind of fact, the table each
        kind of dispatch that ``dispatched_run`` searches is read from.
        A program that also dispatches work under a fact of its own
        names that fact and its table here, so that a completion for
        such work is matched to its workflow run. Each table has a
        dispatch's columns: ``agent_id``, ``step``, ``runner`` and
        ``remote_id``."""
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )
        self._dispatch_tables = dict(
            dispatch_tables
            if dispatch_tables is not None
            else {AGENT_DISPATCHED: AGENT_DISPATCH}
        )

    def events_for_pull_request(
        self, ref: PullRequestRef, event_type: str
    ) -> list[JournalEntry]:
        query = (
            sa.select(*ENTRY_COLUMNS)
            .where(*_about(ref), journal.c.event_type == event_type)
            .order_by(journal.c.occurred_at, journal.c.recorded_at)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return [from_columns(JournalEntry, row) for row in rows]

    def judged_runs(self, ref: PullRequestRef) -> set[Correlation]:
        judged = judge_invocation
        query = (
            sa.select(journal.c.workflow_id, journal.c.run_id)
            .select_from(
                journal.join(judged, judged.c.event_id == journal.c.event_id)
            )
            .where(
                *_about(ref),
                journal.c.event_type == JUDGE_INVOKED,
                judged.c.status.like("judged%"),
            )
            .distinct()
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).all()
        return {
            Correlation(workflow_id=row.workflow_id, run_id=row.run_id)
            for row in rows
        }

    def dispatched_run(
        self, runner: str, remote_id: str
    ) -> DispatchedRun | None:
        for event_type, name in self._dispatch_tables.items():
            dispatch = _dispatch_table(name)
            query = (
                sa.select(
                    journal.c.workflow_id,
                    journal.c.run_id,
                    dispatch.c.agent_id,
                    journal.c.forge,
                    journal.c.repo,
                    journal.c.pr_number,
                    journal.c.commit_sha,
                )
                .select_from(
                    journal.join(
                        dispatch, dispatch.c.event_id == journal.c.event_id
                    )
                )
                .where(
                    journal.c.event_type == event_type,
                    dispatch.c.step == "dispatched",
                    dispatch.c.runner == runner,
                    dispatch.c.remote_id == remote_id,
                )
                .limit(1)
            )
            with self._engine.connect() as connection:
                row = connection.execute(query).first()
            if row is not None:
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
        return None


def _about(ref: PullRequestRef) -> list[sa.ColumnElement[bool]]:
    return [
        journal.c.forge == ref.forge,
        journal.c.repo == f"{ref.owner}/{ref.repo}",
        journal.c.pr_number == ref.number,
    ]
