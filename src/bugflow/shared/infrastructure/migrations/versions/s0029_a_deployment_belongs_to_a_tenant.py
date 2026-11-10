"""Give each policy deployment a tenant (ADR 011).

``policy_deployment``, ``policy_deployment_file`` and
``policy_deployment_in_force`` each gain ``tenant``, and the typed table
``policy_deploy`` gains it too. The column joins the primary key of the
first two and the foreign keys of the second two, so one commit of a
binding may be held for two tenants and each tenant's deployment in
force is read apart. Every row already held is ``default``'s, the tenant
of a server that names none, and the column keeps that default so a
program older than the script writes rows that are still that tenant's.

The downgrade deletes what is held for any other tenant, which the
previous release cannot read, drops the columns and puts the keys back.
"""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"

DEFAULT = "default"

_DEPLOYMENT = ["repository", "commit"]
_FILE = [*_DEPLOYMENT, "path"]
_REFERRING = ("policy_deployment_file", "policy_deployment_in_force")
_TYPED = "policy_deploy"


def _fkey(table: str) -> str:
    return f"{table}_repository_commit_fkey"


def _tenant() -> sa.Column[str]:
    return sa.Column("tenant", sa.Text, nullable=False, server_default=DEFAULT)


def upgrade() -> None:
    for table in _REFERRING:
        op.drop_constraint(_fkey(table), table, type_="foreignkey")
    op.drop_constraint(
        "policy_deployment_file_pkey",
        "policy_deployment_file",
        type_="primary",
    )
    op.drop_constraint(
        "policy_deployment_pkey", "policy_deployment", type_="primary"
    )
    for table in ("policy_deployment", *_REFERRING, _TYPED):
        op.add_column(table, _tenant())
    op.create_primary_key(
        "policy_deployment_pkey", "policy_deployment", ["tenant", *_DEPLOYMENT]
    )
    op.create_primary_key(
        "policy_deployment_file_pkey",
        "policy_deployment_file",
        ["tenant", *_FILE],
    )
    for table in _REFERRING:
        op.create_foreign_key(
            _fkey(table),
            table,
            "policy_deployment",
            ["tenant", *_DEPLOYMENT],
            ["tenant", *_DEPLOYMENT],
        )


def downgrade() -> None:
    for table in (
        "policy_deployment_in_force",
        "policy_deployment_file",
        "policy_deployment",
        _TYPED,
    ):
        op.execute(f"DELETE FROM {table} WHERE tenant <> '{DEFAULT}'")
    for table in _REFERRING:
        op.drop_constraint(_fkey(table), table, type_="foreignkey")
    op.drop_constraint(
        "policy_deployment_file_pkey",
        "policy_deployment_file",
        type_="primary",
    )
    op.drop_constraint(
        "policy_deployment_pkey", "policy_deployment", type_="primary"
    )
    for table in ("policy_deployment", *_REFERRING, _TYPED):
        op.drop_column(table, "tenant")
    op.create_primary_key(
        "policy_deployment_pkey", "policy_deployment", _DEPLOYMENT
    )
    op.create_primary_key(
        "policy_deployment_file_pkey", "policy_deployment_file", _FILE
    )
    for table in _REFERRING:
        op.create_foreign_key(
            _fkey(table),
            table,
            "policy_deployment",
            _DEPLOYMENT,
            _DEPLOYMENT,
        )
