"""Create the table that holds snapshots of pull requests.

A table that is already there is left as it is.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.create_table(
        "pull_request_snapshots",
        sa.Column("snapshot_id", sa.Text, primary_key=True),
        sa.Column(
            "stored_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("body", JSONB, nullable=False),
        if_not_exists=True,
    )
