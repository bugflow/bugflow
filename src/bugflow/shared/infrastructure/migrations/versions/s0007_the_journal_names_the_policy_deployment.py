"""Add three columns to the journal that name the policy deployment a
row was written under, and an index over them.

``policy_repository`` and ``policy_commit`` are the names the sender
gave the deployment. ``policy_content`` is the hash of its files, which
this server computed. With the tables that keep a deployment, they give
the text a fact was judged under.

Each column may be empty and has no default. A row written before this
script has none of the three. Neither has a row written by a process
that started with no deployment in force, or that does not review.

A column or index that is already there is left as it is.
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"

_COLUMNS = ("policy_repository", "policy_commit", "policy_content")


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column("journal", sa.Column(name, sa.Text), if_not_exists=True)
    op.create_index(
        "journal_policy_deployment_idx",
        "journal",
        ["policy_repository", "policy_commit", "occurred_at"],
        if_not_exists=True,
    )
