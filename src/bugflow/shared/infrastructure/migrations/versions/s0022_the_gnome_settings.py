"""Create the tables of what each gnome does on each repository
(ADR 008).

``gnome_setting`` holds one row for each repository and gnome, keyed by
the repository's row of ADR 005, with the gnome's behaviour and the
profile it judges by. ``gnome_setting_change`` is the typed table of
the ``gnome.set`` fact (ADR 007), keyed by the event's id in the policy
journal.

Nothing is filled. ``bugflow settle`` makes the settings from a
server's declarations once the release is deployed, because which
profile a repository's declared policies are is known only by parsing
the deployment in force, and a script does not import the package.

The downgrade drops both tables.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0022"
down_revision = "0021"


def upgrade() -> None:
    op.create_table(
        "gnome_setting",
        sa.Column(
            "repository_id",
            sa.BigInteger,
            sa.ForeignKey("repository.id"),
            primary_key=True,
        ),
        sa.Column("gnome", sa.Text, primary_key=True),
        sa.Column("behaviour", sa.Text, nullable=False),
        sa.Column("profile", sa.Text, nullable=False),
        sa.Column("set_by", sa.Text, nullable=False),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "behaviour IN ('off', 'observe', 'advise', 'gate')",
            name="gnome_setting_behaviour_check",
        ),
    )
    op.create_table(
        "gnome_setting_change",
        sa.Column(
            "event_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("policy_journal.event_id"),
            primary_key=True,
        ),
        sa.Column("gnome", sa.Text, nullable=False),
        sa.Column("behaviour", sa.Text, nullable=False),
        sa.Column("profile", sa.Text, nullable=False),
        sa.Column("set_by", sa.Text, nullable=False),
        sa.Column("was_behaviour", sa.Text),
        sa.Column("was_profile", sa.Text),
    )


def downgrade() -> None:
    op.drop_table("gnome_setting_change")
    op.drop_table("gnome_setting")
