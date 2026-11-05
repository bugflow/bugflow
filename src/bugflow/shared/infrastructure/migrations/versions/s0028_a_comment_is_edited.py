"""Hold the typed rows of the comment the editor wrote (ADR 007).

``comment_edit`` is the typed table of the ``comment.edited`` fact,
keyed by the event's id in the review journal, and
``comment_edit_reviewer`` holds the reviewers whose parts the draft
held, in order. Nothing is filled: no comment was edited before this
script. The downgrade drops the two tables.
"""

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0028"
down_revision = "0027"


def _event_id(references: str) -> sa.Column[UUID]:
    return sa.Column(
        "event_id",
        PG_UUID(as_uuid=True),
        sa.ForeignKey(f"{references}.event_id"),
        primary_key=True,
    )


def upgrade() -> None:
    op.create_table(
        "comment_edit",
        _event_id("review_journal"),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("draft", sa.Text, nullable=False),
        sa.Column("posted", sa.Text, nullable=False),
        sa.Column("model", sa.Text),
    )
    op.create_table(
        "comment_edit_reviewer",
        _event_id("comment_edit"),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("agent_id", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("comment_edit_reviewer")
    op.drop_table("comment_edit")
