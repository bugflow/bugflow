"""Give each gnome's setting a tenant (ADR 012).

``gnome_setting`` gains ``tenant`` in its primary key, so two tenants
that hold a gnome of one id each have a setting of it on a repository,
and the typed table ``gnome_setting_change`` gains the column too. Every
row already held is ``default``'s, the tenant of a server that names
none, and the column keeps that default so a program older than the
script writes rows that are still that tenant's.

The downgrade deletes what is held for any other tenant, which the
previous release cannot tell apart, drops the columns and puts the key
back.
"""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"

DEFAULT = "default"

_SETTING = "gnome_setting"
_CHANGE = "gnome_setting_change"
_KEY = "gnome_setting_pkey"


def _tenant() -> sa.Column[str]:
    return sa.Column("tenant", sa.Text, nullable=False, server_default=DEFAULT)


def upgrade() -> None:
    op.drop_constraint(_KEY, _SETTING, type_="primary")
    op.add_column(_SETTING, _tenant())
    op.add_column(_CHANGE, _tenant())
    op.create_primary_key(_KEY, _SETTING, ["repository_id", "tenant", "gnome"])


def downgrade() -> None:
    for table in (_SETTING, _CHANGE):
        op.execute(f"DELETE FROM {table} WHERE tenant <> '{DEFAULT}'")
    op.drop_constraint(_KEY, _SETTING, type_="primary")
    op.drop_column(_SETTING, "tenant")
    op.drop_column(_CHANGE, "tenant")
    op.create_primary_key(_KEY, _SETTING, ["repository_id", "gnome"])
