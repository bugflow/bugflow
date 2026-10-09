"""The journal in Postgres: fact rows that are appended and never changed.

The table's columns are a published contract: whoever reads the journal
depends on them. A column may be added that existing writers can
ignore; none is removed, retyped or tightened.

The database itself refuses to change a row. Two triggers reject an
update, a delete and a truncate.
"""

from collections.abc import Sequence
from dataclasses import asdict
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.infrastructure.database import engine_url

metadata = sa.MetaData()
journal = sa.Table(
    "journal",
    metadata,
    sa.Column("event_id", PG_UUID(as_uuid=True), primary_key=True),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "recorded_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("event_type", sa.Text, nullable=False),
    sa.Column("forge", sa.Text, nullable=False),
    sa.Column("repo", sa.Text, nullable=False),
    sa.Column("pr_number", sa.Integer),
    sa.Column("commit_sha", sa.Text),
    sa.Column("corpus_version", sa.Text),
    sa.Column("workflow_id", sa.Text, nullable=False),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("agent_id", sa.Text),
    sa.Column("build", sa.Text),
    sa.Index("journal_repo_pr_occurred", "repo", "pr_number", "occurred_at"),
    sa.Index("journal_type_occurred", "event_type", "occurred_at"),
    sa.Index("journal_run", "workflow_id", "run_id"),
    sa.Index("journal_agent_id_idx", "agent_id", "corpus_version"),
    sa.Index("journal_build_idx", "build", "occurred_at"),
)

# Sent to the driver as written, where a percent sign is doubled.
_APPEND_ONLY = (
    """
    CREATE OR REPLACE FUNCTION journal_reject_change() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'journal is append-only: %% rejected', TG_OP;
    END
    $$
    """,
    "CREATE OR REPLACE TRIGGER journal_append_only "
    "BEFORE UPDATE OR DELETE ON journal "
    "FOR EACH ROW EXECUTE FUNCTION journal_reject_change()",
    "CREATE OR REPLACE TRIGGER journal_no_truncate "
    "BEFORE TRUNCATE ON journal "
    "FOR EACH STATEMENT EXECUTE FUNCTION journal_reject_change()",
)


def create_tables(database_url: str) -> None:
    """Create the journal's table in a database that lacks it, and see
    that its triggers are in place. A table already there is left as it
    is."""
    engine = sa.create_engine(engine_url(database_url))
    try:
        metadata.create_all(engine)
        with engine.begin() as connection:
            for statement in _APPEND_ONLY:
                connection.exec_driver_sql(statement)
    finally:
        engine.dispose()


class SqlAlchemyJournal:
    def __init__(self, database_url: str, build: str | None = None) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )
        #: Written on every row this adapter appends. The application
        #: names it, being the one place that knows which build it is.
        self._build = build

    def append(self, entries: Sequence[JournalEntry]) -> None:
        if not entries:
            return
        # The adapter's build, not the entry's: what wrote the row is a
        # fact about this process, so a build an entry arrives with is
        # replaced and not trusted.
        rows = [asdict(entry) | {"build": self._build} for entry in entries]
        statement = (
            insert(journal)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        with self._engine.begin() as connection:
            connection.execute(statement)

    def has_event(self, event_id: UUID) -> bool:
        query = sa.select(sa.exists().where(journal.c.event_id == event_id))
        with self._engine.connect() as connection:
            return bool(connection.execute(query).scalar())
