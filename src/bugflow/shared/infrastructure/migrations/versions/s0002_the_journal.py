"""Create the journal table, its indexes, and the two triggers that make
the database reject any UPDATE, DELETE or TRUNCATE on it.

A table or index that is already there is left as it is. The triggers
are replaced.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0002"
down_revision = "0001"

_INDEXES = {
    "journal_repo_pr_occurred": ["repo", "pr_number", "occurred_at"],
    "journal_type_occurred": ["event_type", "occurred_at"],
    "journal_run": ["workflow_id", "run_id"],
    "journal_agent_id_idx": ["agent_id", "corpus_version"],
    "journal_build_idx": ["build", "occurred_at"],
}


def upgrade() -> None:
    op.create_table(
        "journal",
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
        if_not_exists=True,
    )
    for name, columns in _INDEXES.items():
        op.create_index(name, "journal", columns, if_not_exists=True)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION journal_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'journal is append-only: % rejected', TG_OP;
        END
        $$
        """
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER journal_append_only "
        "BEFORE UPDATE OR DELETE ON journal "
        "FOR EACH ROW EXECUTE FUNCTION journal_reject_change()"
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER journal_no_truncate "
        "BEFORE TRUNCATE ON journal "
        "FOR EACH STATEMENT EXECUTE FUNCTION journal_reject_change()"
    )
