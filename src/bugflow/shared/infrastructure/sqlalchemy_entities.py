"""The journal's entities, each a table with a key of its own.

A journal row names its forge, repository, pull request, workflow and
run in text, and refers to its pull request and its run by key as well
(ADR 005). These tables hold the entities; ``resolve_keys`` finds or
makes the rows an entry refers to.

An entity's identity is its unique constraint, never its key, so a
renamed repository keeps its row.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from bugflow.shared.domain.models.journal_entry import JournalEntry

metadata = sa.MetaData()

forge = sa.Table(
    "forge",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("name", sa.Text, nullable=False, unique=True),
)

repository = sa.Table(
    "repository",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column(
        "forge_id", sa.BigInteger, sa.ForeignKey("forge.id"), nullable=False
    ),
    # owner/name, with no host: the journal's repo.
    sa.Column("name", sa.Text, nullable=False),
    # The canonical origin, host/owner/name, where the journal's rows
    # agree on one. Null where they do not, or none has one.
    sa.Column("origin", sa.Text),
    sa.UniqueConstraint(
        "forge_id", "name", name="repository_forge_id_name_key"
    ),
)

repository_name = sa.Table(
    "repository_name",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column(
        "repository_id",
        sa.BigInteger,
        sa.ForeignKey("repository.id"),
        nullable=False,
    ),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint(
        "repository_id", "name", name="repository_name_repository_id_name_key"
    ),
)

pull_request = sa.Table(
    "pull_request",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column(
        "repository_id",
        sa.BigInteger,
        sa.ForeignKey("repository.id"),
        nullable=False,
    ),
    sa.Column("number", sa.Integer, nullable=False),
    sa.UniqueConstraint(
        "repository_id", "number", name="pull_request_repository_id_number_key"
    ),
)

workflow = sa.Table(
    "workflow",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    # The id the engine gives the workflow: the journal's workflow_id.
    sa.Column("name", sa.Text, nullable=False, unique=True),
)

workflow_run = sa.Table(
    "workflow_run",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column(
        "workflow_id",
        sa.BigInteger,
        sa.ForeignKey("workflow.id"),
        nullable=False,
    ),
    # The id the engine gives the run: the journal's run_id.
    sa.Column("name", sa.Text, nullable=False),
    sa.UniqueConstraint(
        "workflow_id", "name", name="workflow_run_workflow_id_name_key"
    ),
)


def _find_or_make(
    connection: sa.Connection, table: sa.Table, **identity: object
) -> int:
    """The key of the row with this identity, made if it is not there.

    An insert that does nothing on conflict and a select after it, so
    two writers racing to make the same row both read the one that won.
    """
    connection.execute(
        insert(table).values(**identity).on_conflict_do_nothing()
    )
    predicates = [table.c[name] == value for name, value in identity.items()]
    return int(
        connection.execute(
            sa.select(table.c.id).where(*predicates)
        ).scalar_one()
    )


def resolve_keys(
    connection: sa.Connection, entry: JournalEntry
) -> tuple[int | None, int]:
    """The keys of the entry's pull request, or None when it is about
    none, and of its workflow run, each made if it is not there."""
    forge_id = _find_or_make(connection, forge, name=entry.forge)
    repository_id = _find_or_make(
        connection, repository, forge_id=forge_id, name=entry.repo
    )
    connection.execute(
        insert(repository_name)
        .values(
            repository_id=repository_id,
            name=entry.repo,
            first_seen=entry.occurred_at,
        )
        .on_conflict_do_nothing()
    )
    pull_request_id = (
        None
        if entry.pr_number is None
        else _find_or_make(
            connection,
            pull_request,
            repository_id=repository_id,
            number=entry.pr_number,
        )
    )
    workflow_id = _find_or_make(connection, workflow, name=entry.workflow_id)
    workflow_run_id = _find_or_make(
        connection, workflow_run, workflow_id=workflow_id, name=entry.run_id
    )
    return pull_request_id, workflow_run_id
