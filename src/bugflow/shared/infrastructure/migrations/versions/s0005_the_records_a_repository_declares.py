"""Create the tables that hold what a repository is reviewed under: which
reviewers govern its label, which enforcement profile it is bound to,
what share of its warnings is withheld, what it may spend, what it is
judged on and dispatches, and where its periods and the server's own
begin.

A table that is already there is left as it is.
"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"


def _declared_at() -> sa.Column[datetime]:
    return sa.Column(
        "declared_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def upgrade() -> None:
    op.create_table(
        "review_governance",
        sa.Column("forge", sa.Text, primary_key=True),
        sa.Column("repo", sa.Text, primary_key=True),
        sa.Column("agent_id", sa.Text, primary_key=True),
        sa.Column("governs", sa.Boolean, nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        if_not_exists=True,
    )
    op.create_table(
        "repository_enforcement",
        sa.Column("forge", sa.Text, primary_key=True),
        sa.Column("repo", sa.Text, primary_key=True),
        sa.Column("profile", sa.Text, nullable=False),
        _declared_at(),
        if_not_exists=True,
    )
    op.create_table(
        "repository_withholding",
        sa.Column("forge", sa.Text, primary_key=True),
        sa.Column("repo", sa.Text, primary_key=True),
        sa.Column("share", sa.Float, nullable=False),
        _declared_at(),
        if_not_exists=True,
    )
    op.create_table(
        "spend_bindings",
        # Empty rather than null for "any", so the primary key holds:
        # null is not equal to null, and two unscoped rows would both be
        # allowed in.
        sa.Column("forge", sa.Text, primary_key=True, server_default=""),
        sa.Column("repo", sa.Text, primary_key=True, server_default=""),
        sa.Column("layer", sa.Text, primary_key=True, server_default=""),
        sa.Column("agent_id", sa.Text, primary_key=True, server_default=""),
        # A limit, and a null limit is no limit.
        sa.Column("usd", sa.Float),
        sa.Column("turns", sa.Float),
        # What shares the allowance, and part of the key: one scope
        # holds a limit per event and a limit per period.
        sa.Column(
            "per",
            sa.Text,
            primary_key=True,
            nullable=False,
            server_default="event",
        ),
        _declared_at(),
        if_not_exists=True,
    )
    for table, column in (
        ("repository_judged_policies", "policy_id"),
        ("repository_dispatched_processes", "process"),
    ):
        op.create_table(
            table,
            sa.Column("forge", sa.Text, primary_key=True),
            sa.Column("repo", sa.Text, primary_key=True),
            sa.Column(column, sa.Text, primary_key=True),
            _declared_at(),
            if_not_exists=True,
        )
    op.create_table(
        "repository_layer_boundaries",
        sa.Column("forge", sa.Text, primary_key=True),
        sa.Column("repo", sa.Text, primary_key=True),
        sa.Column("layer", sa.Text, primary_key=True),
        sa.Column("boundary", sa.Text, nullable=False),
        _declared_at(),
        if_not_exists=True,
    )
    op.create_table(
        "cadence_boundaries",
        sa.Column("cadence", sa.Text, primary_key=True),
        sa.Column("boundary", sa.Text, nullable=False),
        _declared_at(),
        if_not_exists=True,
    )
