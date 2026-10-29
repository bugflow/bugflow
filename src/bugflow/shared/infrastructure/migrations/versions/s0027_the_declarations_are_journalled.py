"""Hold the typed rows of what an operator declares (ADR 007).

``boundary_declaration``, ``cadence_declaration``,
``withholding_declaration`` and ``allowance_declaration`` are the typed
tables of the ``boundary.declared``, ``cadence.declared``,
``withholding.declared`` and ``allowance.declared`` facts, keyed by the
event's id in the policy journal. Nothing is filled: the declarations
made before this script have no facts. The downgrade drops the tables.
"""

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0027"
down_revision = "0026"

TABLES = (
    "boundary_declaration",
    "cadence_declaration",
    "withholding_declaration",
    "allowance_declaration",
)


def _event_id() -> sa.Column[UUID]:
    return sa.Column(
        "event_id",
        PG_UUID(as_uuid=True),
        sa.ForeignKey("policy_journal.event_id"),
        primary_key=True,
    )


def upgrade() -> None:
    op.create_table(
        "boundary_declaration",
        _event_id(),
        sa.Column("layer", sa.Text, nullable=False),
        sa.Column("boundary", sa.Text),
        sa.Column("was", sa.Text),
        sa.Column("declared_by", sa.Text, nullable=False),
    )
    op.create_table(
        "cadence_declaration",
        _event_id(),
        sa.Column("cadence", sa.Text, nullable=False),
        sa.Column("boundary", sa.Text),
        sa.Column("was", sa.Text),
        sa.Column("declared_by", sa.Text, nullable=False),
    )
    op.create_table(
        "withholding_declaration",
        _event_id(),
        sa.Column("share", sa.Float, nullable=False),
        sa.Column("was", sa.Float),
        sa.Column("declared_by", sa.Text, nullable=False),
    )
    op.create_table(
        "allowance_declaration",
        _event_id(),
        sa.Column("owner", sa.Text, nullable=False),
        sa.Column("layer", sa.Text, nullable=False),
        sa.Column("agent_id", sa.Text, nullable=False),
        sa.Column("per", sa.Text, nullable=False),
        sa.Column("held", sa.Boolean, nullable=False),
        sa.Column("usd", sa.Float),
        sa.Column("turns", sa.Float),
        sa.Column("was_held", sa.Boolean, nullable=False),
        sa.Column("was_usd", sa.Float),
        sa.Column("was_turns", sa.Float),
        sa.Column("declared_by", sa.Text, nullable=False),
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
