"""Create the tables that hold judge exchanges and write-ups.

A table that is already there is left as it is.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.create_table(
        "judge_exchanges",
        sa.Column("exchange_id", sa.Text, primary_key=True),
        sa.Column(
            "stored_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("request", JSONB, nullable=False),
        sa.Column("response", JSONB, nullable=False),
        if_not_exists=True,
    )
    op.create_table(
        "agent_write_ups",
        sa.Column("write_up_id", sa.Text, primary_key=True),
        sa.Column(
            "stored_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("workflow_id", sa.Text, nullable=False),
        sa.Column("run_id", sa.Text, nullable=False),
        sa.Column("agent_id", sa.Text, nullable=False),
        sa.Column("write_up", sa.Text, nullable=False),
        if_not_exists=True,
    )
