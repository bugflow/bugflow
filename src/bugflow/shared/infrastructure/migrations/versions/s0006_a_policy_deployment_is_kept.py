"""Create the tables that keep what a policy repository deployed to this
server: a deployment by the names it was sent under, its files one row
each, and one row for each time a deployment was put in force. The
latest of those rows says which deployment is in force. A server with no
row was never sent one and reviews nothing.

A table that is already there is left as it is.
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.create_table(
        "policy_deployments",
        sa.Column("repository", sa.Text, primary_key=True),
        sa.Column("commit", sa.Text, primary_key=True),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        if_not_exists=True,
    )
    op.create_table(
        "policy_deployment_files",
        sa.Column("repository", sa.Text, primary_key=True),
        sa.Column("commit", sa.Text, primary_key=True),
        sa.Column("path", sa.Text, primary_key=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(
            ["repository", "commit"],
            ["policy_deployments.repository", "policy_deployments.commit"],
        ),
        if_not_exists=True,
    )
    op.create_table(
        "policy_deployments_in_force",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("repository", sa.Text, nullable=False),
        sa.Column("commit", sa.Text, nullable=False),
        sa.Column(
            "put_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["repository", "commit"],
            ["policy_deployments.repository", "policy_deployments.commit"],
        ),
        if_not_exists=True,
    )
