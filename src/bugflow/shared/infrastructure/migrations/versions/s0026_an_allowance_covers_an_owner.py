"""Let an allowance cover every repository of one owner.

``spend_binding`` gains ``owner``, empty for an allowance that names no
owner, and the column joins the primary key, so that one owner's
allowance and everything's are two rows. Every row already held names
no owner, and nothing is filled.

The downgrade deletes the allowances that name an owner, which the
previous release cannot read, and drops the column.
"""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"

_KEY = ["forge", "repo", "layer", "agent_id", "per"]


def upgrade() -> None:
    op.add_column(
        "spend_binding",
        sa.Column("owner", sa.Text, nullable=False, server_default=""),
    )
    op.drop_constraint("spend_binding_pkey", "spend_binding", type_="primary")
    op.create_primary_key(
        "spend_binding_pkey", "spend_binding", ["forge", "owner", *_KEY[1:]]
    )


def downgrade() -> None:
    op.execute("DELETE FROM spend_binding WHERE owner <> ''")
    op.drop_constraint("spend_binding_pkey", "spend_binding", type_="primary")
    op.drop_column("spend_binding", "owner")
    op.create_primary_key("spend_binding_pkey", "spend_binding", _KEY)
