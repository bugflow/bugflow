"""The journal stored in a Postgres table.

Other software reads this table, so its columns are a contract. A new
column may be added if existing writers can ignore it. No column is
removed, changed in type, or made stricter.

The database itself stops a row being changed: two triggers reject any
UPDATE, DELETE or TRUNCATE on the table. The table and its triggers are
made by the scripts in ``migrations``.
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
    sa.Column("policy_repository", sa.Text),
    sa.Column("policy_commit", sa.Text),
    sa.Column("policy_content", sa.Text),
    sa.Index("journal_repo_pr_occurred", "repo", "pr_number", "occurred_at"),
    sa.Index("journal_type_occurred", "event_type", "occurred_at"),
    sa.Index("journal_run", "workflow_id", "run_id"),
    sa.Index("journal_agent_id_idx", "agent_id", "corpus_version"),
    sa.Index("journal_build_idx", "build", "occurred_at"),
    sa.Index(
        "journal_policy_deployment_idx",
        "policy_repository",
        "policy_commit",
        "occurred_at",
    ),
)

#: The columns that are not fields of a ``JournalEntry``: the time the
#: database stored the row, and the policy deployment the writing
#: process started with.
_NOT_OF_AN_ENTRY = frozenset(
    {"recorded_at", "policy_repository", "policy_commit", "policy_content"}
)

#: The columns a ``JournalEntry`` is built from, for an adapter that
#: reads entries back.
ENTRY_COLUMNS = tuple(
    column for column in journal.c if column.name not in _NOT_OF_AN_ENTRY
)


class SqlAlchemyJournal:
    def __init__(
        self,
        database_url: str,
        build: str | None = None,
        policy_repository: str | None = None,
        policy_commit: str | None = None,
        policy_content: str | None = None,
    ) -> None:
        """``build`` is stored in the ``build`` column of every row this
        adapter writes.

        ``policy_repository``, ``policy_commit`` and ``policy_content``
        name the policy deployment the writing process started with:
        the names its sender gave it, and the hash of its files. They
        are stored on every row too. All three are None for a process
        that started with no deployment in force, or that does not
        review.

        The application passes each of them in.
        """
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )
        self._stamps = {
            "build": build,
            "policy_repository": policy_repository,
            "policy_commit": policy_commit,
            "policy_content": policy_content,
        }

    def append(self, entries: Sequence[JournalEntry]) -> None:
        if not entries:
            return
        # Always store this adapter's build, even if the entry carries
        # one: the build is about the process doing the writing.
        rows = [asdict(entry) | self._stamps for entry in entries]
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
