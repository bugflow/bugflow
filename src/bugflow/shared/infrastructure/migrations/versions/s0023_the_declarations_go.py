"""Drop the records a repository declared before ADR 008: the policies
it was judged on, the processes it dispatched, the profile it was bound
to and which reviewers governed its label.

Each gnome's setting on a repository says all of these since script
0022, and ``bugflow settle``, in the release that made the settings,
made them from these records. The check stops on a repository that
declared a policy and has no setting, so no server loses what it
reviewed by when it skips the settle. Run the previous release's
``bugflow settle`` and this script again. A repository bound to a
profile with no policy declared was judged on nothing and is let
through.

The downgrade makes the four tables again, empty, as 0005 and 0009 left
them. What they held is not put back: the settings hold it now.
"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"

#: The tables of what a repository declared.
JUDGED = "repository_judged_policy"
DISPATCHED = "repository_dispatched_process"
ENFORCEMENT = "repository_enforcement"
GOVERNANCE = "review_governance"


def _unsettled(connection: sa.Connection) -> list[str]:
    """The repositories that declared a policy and have no setting."""
    rows = connection.execute(
        sa.text(
            f"""
            SELECT DISTINCT d.forge, d.repo
            FROM {JUDGED} AS d
            WHERE NOT EXISTS (
                SELECT 1
                FROM gnome_setting AS s
                JOIN repository AS r ON r.id = s.repository_id
                JOIN forge AS f ON f.id = r.forge_id
                WHERE f.name = d.forge AND r.name = d.repo
            )
            ORDER BY d.forge, d.repo
            """
        )
    )
    return [f"{forge}:{repo}" for forge, repo in rows]


def upgrade() -> None:
    unsettled = _unsettled(op.get_bind())
    if unsettled:
        raise RuntimeError(
            f"{', '.join(unsettled)} declared what it is reviewed for and "
            "has no gnome setting. Run bugflow settle with the release "
            "before this one, then this script again"
        )
    for table in (JUDGED, DISPATCHED, ENFORCEMENT, GOVERNANCE):
        op.drop_table(table)


def _declared_at() -> sa.Column[datetime]:
    return sa.Column(
        "declared_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def downgrade() -> None:
    op.create_table(
        GOVERNANCE,
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
    )
    op.create_table(
        ENFORCEMENT,
        sa.Column("forge", sa.Text, primary_key=True),
        sa.Column("repo", sa.Text, primary_key=True),
        sa.Column("profile", sa.Text, nullable=False),
        _declared_at(),
    )
    for table, column in ((JUDGED, "policy_id"), (DISPATCHED, "process")):
        op.create_table(
            table,
            sa.Column("forge", sa.Text, primary_key=True),
            sa.Column("repo", sa.Text, primary_key=True),
            sa.Column(column, sa.Text, primary_key=True),
            _declared_at(),
        )
