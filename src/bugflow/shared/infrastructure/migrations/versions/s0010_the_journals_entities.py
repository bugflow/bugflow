"""Give the journal's entities tables of their own, and the journal keys
to them (ADR 005).

Creates forge, repository, repository_name, pull_request, workflow and
workflow_run, each with a generated key and its identity held by a
unique constraint, and fills them from the journal's distinct values.
Then gives the journal pull_request_id, null for a row about no pull
request, and workflow_run_id, and fills both from the text columns.
Both are nullable, since a column added to the journal must not break
a writer that does not know it.

The journal's triggers reject an update. They guard programs, and this
script is not one, so it disables them for its transaction and enables
them after, which is written here and in the version table.

A repository's origin is filled where every associated journal row of
the repository names the same one, and left null where they disagree or
none has one.

The downgrade drops the two columns and the six tables.
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"

_TRIGGERS = ("journal_append_only", "journal_no_truncate")


def upgrade() -> None:
    op.create_table(
        "forge",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
    )
    op.create_table(
        "repository",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column(
            "forge_id",
            sa.BigInteger,
            sa.ForeignKey("forge.id"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("origin", sa.Text),
        sa.UniqueConstraint(
            "forge_id", "name", name="repository_forge_id_name_key"
        ),
    )
    op.create_table(
        "repository_name",
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
            "repository_id",
            "name",
            name="repository_name_repository_id_name_key",
        ),
    )
    op.create_table(
        "pull_request",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column(
            "repository_id",
            sa.BigInteger,
            sa.ForeignKey("repository.id"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer, nullable=False),
        sa.UniqueConstraint(
            "repository_id",
            "number",
            name="pull_request_repository_id_number_key",
        ),
    )
    op.create_table(
        "workflow",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
    )
    op.create_table(
        "workflow_run",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.BigInteger,
            sa.ForeignKey("workflow.id"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.UniqueConstraint(
            "workflow_id", "name", name="workflow_run_workflow_id_name_key"
        ),
    )

    # The entities, from what the journal names.
    op.execute("INSERT INTO forge (name) SELECT DISTINCT forge FROM journal")
    op.execute(
        """
        INSERT INTO repository (forge_id, name)
        SELECT DISTINCT f.id, j.repo
        FROM journal j JOIN forge f ON f.name = j.forge
        """
    )
    op.execute(
        """
        INSERT INTO repository_name (repository_id, name, first_seen)
        SELECT r.id, r.name, min(j.occurred_at)
        FROM journal j
        JOIN forge f ON f.name = j.forge
        JOIN repository r ON r.forge_id = f.id AND r.name = j.repo
        GROUP BY r.id, r.name
        """
    )
    op.execute(
        """
        INSERT INTO pull_request (repository_id, number)
        SELECT DISTINCT r.id, j.pr_number
        FROM journal j
        JOIN forge f ON f.name = j.forge
        JOIN repository r ON r.forge_id = f.id AND r.name = j.repo
        WHERE j.pr_number IS NOT NULL
        """
    )
    op.execute(
        "INSERT INTO workflow (name) SELECT DISTINCT workflow_id FROM journal"
    )
    op.execute(
        """
        INSERT INTO workflow_run (workflow_id, name)
        SELECT DISTINCT w.id, j.run_id
        FROM journal j JOIN workflow w ON w.name = j.workflow_id
        """
    )
    # A repository's origin, where its associated rows agree on one.
    op.execute(
        """
        UPDATE repository r SET origin = agreed.origin
        FROM (
            SELECT r.id, min(a.origin) AS origin
            FROM repository r
            JOIN forge f ON f.id = r.forge_id
            JOIN journal j ON j.forge = f.name AND j.repo = r.name
            JOIN repository_association a
              ON a.kind = 'journal' AND a.record_id = j.event_id::text
            GROUP BY r.id
            HAVING count(DISTINCT a.origin) = 1
        ) agreed
        WHERE r.id = agreed.id
        """
    )

    # The journal's keys.
    op.add_column(
        "journal",
        sa.Column(
            "pull_request_id", sa.BigInteger, sa.ForeignKey("pull_request.id")
        ),
    )
    op.add_column(
        "journal",
        sa.Column(
            "workflow_run_id", sa.BigInteger, sa.ForeignKey("workflow_run.id")
        ),
    )
    for trigger in _TRIGGERS:
        op.execute(f"ALTER TABLE journal DISABLE TRIGGER {trigger}")
    op.execute(
        """
        UPDATE journal j
        SET pull_request_id = p.id
        FROM forge f, repository r, pull_request p
        WHERE f.name = j.forge
          AND r.forge_id = f.id AND r.name = j.repo
          AND p.repository_id = r.id AND p.number = j.pr_number
        """
    )
    op.execute(
        """
        UPDATE journal j
        SET workflow_run_id = wr.id
        FROM workflow w, workflow_run wr
        WHERE w.name = j.workflow_id
          AND wr.workflow_id = w.id AND wr.name = j.run_id
        """
    )
    for trigger in _TRIGGERS:
        op.execute(f"ALTER TABLE journal ENABLE TRIGGER {trigger}")
    op.create_index(
        "journal_pull_request_occurred",
        "journal",
        ["pull_request_id", "occurred_at"],
    )
    op.create_index("journal_workflow_run", "journal", ["workflow_run_id"])


def downgrade() -> None:
    op.drop_index("journal_workflow_run", "journal")
    op.drop_index("journal_pull_request_occurred", "journal")
    op.drop_column("journal", "workflow_run_id")
    op.drop_column("journal", "pull_request_id")
    for table in (
        "workflow_run",
        "workflow",
        "pull_request",
        "repository_name",
        "repository",
        "forge",
    ):
        op.drop_table(table)
