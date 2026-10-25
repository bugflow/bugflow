"""The forge context's questions of the journal, answered from the
journal's Postgres table.

This class only reads. Writing to the journal is done by
``bugflow.shared.infrastructure.sqlalchemy_journal.SqlAlchemyJournal``.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from bugflow.forge.domain import facts
from bugflow.forge.domain.models.judgement import RecordedJudgement
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.serde import from_columns
from bugflow.shared.infrastructure.sqlalchemy_journal import (
    ENTRY_COLUMNS,
    journal,
)
from bugflow.shared.infrastructure.sqlalchemy_repository_associations import (
    association_exists,
)

#: The review's table a judgement is read from (ADR 007), named with the
#: columns this context reads. The review context defines the table.
judge_invocation = sa.table(
    "judge_invocation",
    sa.column("event_id", PG_UUID(as_uuid=True)),
    sa.column("policy_id", sa.Text),
    sa.column("identity_input_hash", sa.Text),
    sa.column("status", sa.Text),
)


class SqlAlchemyJournalQueries:
    """Answer the journal questions declared by the forge context."""

    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

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

    def judgements_for_pull_request(
        self, ref: PullRequestRef
    ) -> list[RecordedJudgement]:
        judged = judge_invocation
        query = (
            sa.select(
                judged.c.policy_id,
                judged.c.identity_input_hash,
                judged.c.status,
                journal.c.corpus_version,
            )
            .select_from(
                journal.join(judged, judged.c.event_id == journal.c.event_id)
            )
            .where(
                journal.c.forge == ref.forge,
                journal.c.repo == f"{ref.owner}/{ref.repo}",
                journal.c.pr_number == ref.number,
                journal.c.event_type == facts.JUDGE_INVOKED,
            )
            .order_by(journal.c.occurred_at, journal.c.recorded_at)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).all()
        return [
            RecordedJudgement(
                policy_id=row.policy_id,
                input_hash=row.identity_input_hash,
                status=row.status,
                corpus_version=row.corpus_version,
            )
            for row in rows
        ]

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

    def repositories_with_origin(
        self, event_type: str, origin_endpoint: str
    ) -> list[tuple[str, str]]:
        prefix = origin_endpoint.rstrip("/") + "/"
        query = (
            sa.select(journal.c.forge, journal.c.repo)
            .where(
                journal.c.event_type == event_type,
                association_exists(
                    "journal",
                    sa.cast(journal.c.event_id, sa.Text),
                    sa.func.concat(prefix, journal.c.repo),
                ),
            )
            .distinct()
            .order_by(journal.c.forge, journal.c.repo)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).all()
        return [(row.forge, row.repo) for row in rows]

    def received_since(
        self,
        ref: PullRequestRef,
        since: datetime,
        *,
        origin: str | None = None,
    ) -> bool:
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
        if origin is not None:
            query = query.where(
                association_exists(
                    "journal", sa.cast(journal.c.event_id, sa.Text), origin
                )
            )
        with self._engine.connect() as connection:
            return connection.execute(query).first() is not None
