"""The journal stored in Postgres: one table for each kind of fact, and
a view named ``journal`` over them all (ADR 006).

Other software reads the view, so its columns are a contract. A new
column may be added if existing writers can ignore it. No column is
removed, changed in type, or made stricter, with one exception: a
journal's ``payload`` column goes once a table holds each of its types,
and the view reads null for it (ADR 007).

A fact is written to the table of its kind, by the map in the shared
kernel. The database itself stops a row being changed: two triggers on
each table reject any UPDATE, DELETE or TRUNCATE. The tables, the view
and the triggers are made by the scripts in ``migrations``.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.schema import SchemaItem

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.models.journal_kind import KINDS, journal_of
from bugflow.shared.domain.models.journal_provenance import (
    JournalScope,
    check_retry,
    resolve_origin,
    scope_of,
    validate_assertion,
)
from bugflow.shared.domain.values.repository_association import (
    RepositoryAssociation,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.sqlalchemy_entities import (
    metadata as metadata,
)
from bugflow.shared.infrastructure.sqlalchemy_entities import resolve_keys
from bugflow.shared.infrastructure.sqlalchemy_repository_associations import (
    associate_on_connection,
    repository_associations,
)


def _journal_table(
    name: str, into: sa.MetaData, indexed: bool, payload: bool = True
) -> sa.Table:
    """A table of the journal's shape. The five kinds' tables are
    indexed; the view over them is described without indexes, for
    reading. ``payload`` is False for a journal whose payload column has
    gone (ADR 007)."""
    columns: list[SchemaItem] = [
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
        *([sa.Column("payload", JSONB, nullable=False)] if payload else []),
        sa.Column("agent_id", sa.Text),
        sa.Column("build", sa.Text),
        sa.Column("policy_repository", sa.Text),
        sa.Column("policy_commit", sa.Text),
        sa.Column("policy_content", sa.Text),
        # The entities the text columns name, by key (ADR 005). A row
        # about no pull request has no pull_request_id, and a row an
        # older writer wrote has neither, since a new column must not
        # break one.
        sa.Column(
            "pull_request_id", sa.BigInteger, sa.ForeignKey("pull_request.id")
        ),
        sa.Column(
            "workflow_run_id", sa.BigInteger, sa.ForeignKey("workflow_run.id")
        ),
    ]
    if indexed:
        columns += [
            sa.Index(
                f"{name}_repo_pr_occurred", "repo", "pr_number", "occurred_at"
            ),
            sa.Index(
                f"{name}_pull_request_occurred",
                "pull_request_id",
                "occurred_at",
            ),
            sa.Index(f"{name}_workflow_run", "workflow_run_id"),
            sa.Index(f"{name}_type_occurred", "event_type", "occurred_at"),
            sa.Index(f"{name}_run", "workflow_id", "run_id"),
            sa.Index(f"{name}_agent_id_idx", "agent_id", "corpus_version"),
            sa.Index(f"{name}_build_idx", "build", "occurred_at"),
            sa.Index(
                f"{name}_policy_deployment_idx",
                "policy_repository",
                "policy_commit",
                "occurred_at",
            ),
        ]
    return sa.Table(name, into, *columns)


#: The journals whose payload column has gone, a table holding each of
#: their types (ADR 007): the archive's, by script 0017, and the
#: forge's, by 0018.
WITHOUT_PAYLOAD = frozenset({"archive", "forge"})

# The journals share their metadata with the entity tables they refer to
# by key (ADR 005).
JOURNALS: dict[str, sa.Table] = {
    kind: _journal_table(
        f"{kind}_journal",
        metadata,
        indexed=True,
        payload=kind not in WITHOUT_PAYLOAD,
    )
    for kind in KINDS
}

#: What readers read: the view over the five journals, with the columns
#: the one table had, and null for the payload of a journal whose column
#: has gone. Described apart from the tables, since it is not one and
#: the scripts are not compared with it.
views = sa.MetaData()
journal = _journal_table("journal", views, indexed=False)


#: Tables of the journal's shape a deployment keeps beside the package's
#: five, described as they are first named.
_deployments = sa.MetaData()


#: What writes a type's typed row from its envelope, in the envelope's
#: transaction: a function of the connection and the entry (ADR 007).
Unpacker = Callable[[sa.Connection, JournalEntry], None]


def table_for(
    event_type: str, placements: Mapping[str, str] | None = None
) -> sa.Table:
    """The journal a fact of this type is written to: the package's for a
    type its map places, else the deployment's own placement, a table of
    the journal's shape, else a refusal."""
    if placements and event_type in placements:
        name = placements[event_type]
        if name in metadata.tables:
            return metadata.tables[name]
        if name not in _deployments.tables:
            _journal_table(name, _deployments, indexed=False)
        return _deployments.tables[name]
    return metadata.tables[journal_of(event_type)]


#: The columns that are not fields of a ``JournalEntry``: the time the
#: database stored the row, the policy deployment the writing process
#: started with, and the keys of the entities the entry names in text.
_NOT_OF_AN_ENTRY = frozenset(
    {
        "recorded_at",
        "policy_repository",
        "policy_commit",
        "policy_content",
        "pull_request_id",
        "workflow_run_id",
    }
)


def _entry_column(column: sa.Column[Any]) -> sa.ColumnElement[Any]:
    """The view's column as an entry's field: a payload the view reads
    null for, since the journal's column has gone, is an empty one."""
    if column.name == "payload":
        return sa.func.coalesce(
            column, sa.cast(sa.literal("{}"), JSONB)
        ).label("payload")
    return column


#: The columns a ``JournalEntry`` is built from, for an adapter that
#: reads entries back.
ENTRY_COLUMNS: tuple[sa.ColumnElement[Any], ...] = tuple(
    _entry_column(column)
    for column in journal.c
    if column.name not in _NOT_OF_AN_ENTRY
)

#: Every column of the view, the payload read as an entry's, for an
#: adapter that reads entries back with what the database recorded
#: about them.
VIEW_COLUMNS: tuple[sa.ColumnElement[Any], ...] = tuple(
    _entry_column(column) for column in journal.c
)


class SqlAlchemyJournal:
    def __init__(
        self,
        database_url: str,
        build: str | None = None,
        policy_repository: str | None = None,
        policy_commit: str | None = None,
        policy_content: str | None = None,
        placements: Mapping[str, str] | None = None,
        unpackers: Mapping[str, Unpacker] | None = None,
    ) -> None:
        """``build`` is stored in the ``build`` column of every row this
        adapter writes.

        ``placements`` names the journal each of a deployment's own event
        types is written to, by table: one of the package's five, or a
        table of the journal's shape the deployment's own scripts made.
        A type neither the package's map nor the placements name is
        refused.

        ``unpackers`` writes each type's typed row from the entry's
        payload, in the envelope's transaction (ADR 007). A type with no
        unpacker has no typed table yet. A journal whose payload column
        has gone stores the envelope without the payload, and the typed
        row is where the fact is read.

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
        self._placements = dict(placements or {})
        self._unpackers = dict(unpackers or {})
        self._stamps = {
            "build": build,
            "policy_repository": policy_repository,
            "policy_commit": policy_commit,
            "policy_content": policy_content,
        }

    def append(self, entries: Sequence[JournalEntry]) -> None:
        for entry in entries:
            validate_assertion(entry)
        if not entries:
            return
        scopes = {scope_of(entry) for entry in entries}
        table = repository_associations
        joined = journal.outerjoin(
            table,
            sa.and_(
                table.c.kind == "journal",
                table.c.record_id == sa.cast(journal.c.event_id, sa.Text),
            ),
        )
        with self._engine.begin() as connection:
            # Serialize first writers as well as retries. Row locks alone
            # cannot lock a run whose first event has not been inserted.
            for key in sorted(
                json.dumps(("journal-origin", *scope))
                for scope in scopes
                if scope[0] and scope[1]
            ):
                connection.execute(
                    sa.select(
                        sa.func.pg_advisory_xact_lock(
                            sa.func.hashtextextended(key, 0)
                        )
                    )
                )
            origins: dict[JournalScope, str | None] = {}
            for scope in scopes:
                if not scope[0] or not scope[1]:
                    origins[scope] = None
                    continue
                retained = (
                    connection.execute(
                        sa.select(table.c.origin)
                        .select_from(joined)
                        .where(*_scope_predicates(scope))
                        .distinct()
                    )
                    .scalars()
                    .all()
                )
                origins[scope] = resolve_origin(
                    scope,
                    (
                        entry.origin
                        for entry in entries
                        if scope_of(entry) == scope
                        and (entry.origin is not None or entry.origin_asserted)
                    ),
                    retained,
                )
            # Stable event order prevents overlapping batches from taking
            # unique-index locks in opposite orders.
            for entry in sorted(entries, key=lambda one: str(one.event_id)):
                row = asdict(entry) | self._stamps
                row.pop("origin")
                row.pop("origin_asserted")
                pull_request_id, workflow_run_id = resolve_keys(
                    connection, entry
                )
                row["pull_request_id"] = pull_request_id
                row["workflow_run_id"] = workflow_run_id
                into = table_for(entry.event_type, self._placements)
                if "payload" not in into.c:
                    row.pop("payload")
                inserted = connection.execute(
                    insert(into)
                    .values(row)
                    .on_conflict_do_nothing(index_elements=["event_id"])
                    .returning(into.c.event_id)
                ).scalar_one_or_none()
                if inserted is None:
                    if entry.origin is not None or entry.origin_asserted:
                        held = connection.execute(
                            sa.select(
                                journal.c.workflow_id,
                                journal.c.run_id,
                                journal.c.forge,
                                journal.c.repo,
                                journal.c.pr_number,
                                table.c.origin,
                            )
                            .select_from(joined)
                            .where(journal.c.event_id == entry.event_id)
                        ).one()
                        check_retry(
                            entry,
                            (
                                held.workflow_id,
                                held.run_id,
                                held.forge,
                                held.repo,
                                held.pr_number,
                            ),
                            held.origin,
                        )
                    continue
                unpack = self._unpackers.get(entry.event_type)
                if unpack is not None:
                    unpack(connection, entry)
                origin = origins[scope_of(entry)]
                if origin is not None:
                    associate_on_connection(
                        connection,
                        (
                            RepositoryAssociation(
                                kind="journal",
                                record_id=str(entry.event_id),
                                origin=RepositoryOrigin(origin),
                            ),
                        ),
                    )

    def has_event(self, event_id: UUID) -> bool:
        query = sa.select(sa.exists().where(journal.c.event_id == event_id))
        with self._engine.connect() as connection:
            return bool(connection.execute(query).scalar())


def _scope_predicates(scope: JournalScope) -> list[sa.ColumnElement[bool]]:
    workflow_id, run_id, forge, repo, number = scope
    return [
        journal.c.workflow_id == workflow_id,
        journal.c.run_id == run_id,
        journal.c.forge == forge,
        journal.c.repo == repo,
        journal.c.pr_number == number,
    ]
