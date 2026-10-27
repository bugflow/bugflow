"""Hold what discovery learns of a repository at its forge (ADR 008).

``repository`` gains ``forge_key``, the forge's own id for the
repository, which a rename keeps, so a renamed repository is found by
it and keeps its row; and ``archived``. ``repository_finding`` is the
typed table of the ``repository.found`` fact (ADR 007), keyed by the
event's id in the forge journal.

Nothing is filled: discovery fills each repository's key the first time
it lists it. The downgrade drops the table and the two columns.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0024"
down_revision = "0023"


def upgrade() -> None:
    op.add_column("repository", sa.Column("forge_key", sa.Text))
    op.add_column(
        "repository",
        sa.Column(
            "archived", sa.Boolean, nullable=False, server_default=sa.false()
        ),
    )
    op.create_unique_constraint(
        "repository_forge_id_forge_key_key",
        "repository",
        ["forge_id", "forge_key"],
    )
    op.create_table(
        "repository_finding",
        sa.Column(
            "event_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("forge_journal.event_id"),
            primary_key=True,
        ),
        sa.Column("change", sa.Text, nullable=False),
        sa.Column("forge_key", sa.Text, nullable=False),
        sa.Column("archived", sa.Boolean, nullable=False),
        sa.Column("was_name", sa.Text),
    )


def downgrade() -> None:
    op.drop_table("repository_finding")
    op.drop_constraint(
        "repository_forge_id_forge_key_key", "repository", type_="unique"
    )
    op.drop_column("repository", "archived")
    op.drop_column("repository", "forge_key")
