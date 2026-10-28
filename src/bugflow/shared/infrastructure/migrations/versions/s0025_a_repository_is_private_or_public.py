"""Hold whether a repository is private at its forge (ADR 008).

``repository`` gains ``private``, which discovery sets each time it
lists the repository, so the settings page can say which repositories
anyone may read. It is null for a repository known from the journal and
not yet listed. The downgrade drops the column.
"""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"


def upgrade() -> None:
    op.add_column("repository", sa.Column("private", sa.Boolean))


def downgrade() -> None:
    op.drop_column("repository", "private")
