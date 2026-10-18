"""Associate retained records without changing their bytes or identifiers."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.create_table(
        "repository_associations",
        sa.Column("kind", sa.Text, primary_key=True),
        sa.Column("record_id", sa.Text, primary_key=True),
        sa.Column("origin", sa.Text, nullable=False),
        sa.Column(
            "associated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("kind IN ('journal', 'snapshot', 'ledger')"),
        sa.CheckConstraint("record_id <> '' AND origin <> ''"),
        if_not_exists=True,
    )
    op.create_index(
        "repository_associations_origin_idx",
        "repository_associations",
        ["origin", "kind"],
        if_not_exists=True,
    )
