"""Create the archive's tables.

A table or index that is already there is left as it is.
"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None


def _now(name: str) -> sa.Column[datetime]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def upgrade() -> None:
    op.create_table(
        "archive_bindings",
        sa.Column("ledger_id", sa.Text, primary_key=True),
        sa.Column("forge", sa.Text, nullable=False),
        sa.Column("repo", sa.Text, nullable=False),
        sa.Column("scope", sa.Text, nullable=False),
        _now("declared_at"),
        if_not_exists=True,
    )
    op.create_table(
        "archive_events",
        sa.Column("ledger_id", sa.Text, primary_key=True),
        sa.Column("number", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("data", sa.LargeBinary, nullable=False),
        sa.Column("claims", JSONB, nullable=False),
        sa.Column("caller", sa.Text, nullable=False),
        _now("accepted_at"),
        if_not_exists=True,
    )
    op.create_table(
        "archive_block_puts",
        sa.Column("ledger_id", sa.Text, primary_key=True),
        sa.Column("cid", sa.Text, primary_key=True),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("caller", sa.Text, nullable=False),
        sa.Column("new", sa.Boolean, nullable=False),
        _now("put_at"),
        if_not_exists=True,
    )
    op.create_table(
        "archive_index_files",
        sa.Column("cid", sa.Text, primary_key=True),
        sa.Column("lines", sa.Integer, nullable=False),
        sa.Column("text", sa.Boolean, nullable=False),
        _now("indexed_at"),
        if_not_exists=True,
    )
    op.create_table(
        "archive_index_lines",
        sa.Column("cid", sa.Text, primary_key=True),
        sa.Column("number", sa.Integer, primary_key=True),
        sa.Column("text", sa.Text, nullable=False),
        if_not_exists=True,
    )
    op.create_table(
        "archive_index_positions",
        sa.Column("ledger_id", sa.Text, primary_key=True),
        sa.Column("events", sa.Integer, nullable=False),
        _now("indexed_at"),
        if_not_exists=True,
    )
