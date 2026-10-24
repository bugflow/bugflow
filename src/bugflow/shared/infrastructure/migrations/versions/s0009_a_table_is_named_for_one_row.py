"""Name each table for what one of its rows is.

A table named for its collection, ``spend_bindings``, says what the
table holds; one named for a row, ``spend_binding``, says what a row
is, which is what a query joins, inserts and reads. Eighteen tables
were named for the collection. The journal, the review governance, the
repository enforcement and the repository withholding already were
named for a row.

Each table is renamed, and with it the one index and every constraint
that carried the old name: a primary key, a check or a foreign key
that Postgres named ``<table>_<...>`` when the table was created, and
a primary key named another way by an earlier chain of scripts, which
takes the new table's name. No data moves.

The downgrade puts every name back, so a deployment can return to the
previous tag.
"""

from alembic import op

revision = "0009"
down_revision = "0008"

#: The old name of each table and the new one.
RENAMED = {
    "agent_write_ups": "agent_write_up",
    "archive_bindings": "archive_binding",
    "archive_block_puts": "archive_block_put",
    "archive_events": "archive_event",
    "archive_index_files": "archive_index_file",
    "archive_index_lines": "archive_index_line",
    "archive_index_positions": "archive_index_position",
    "cadence_boundaries": "cadence_boundary",
    "judge_exchanges": "judge_exchange",
    "policy_deployment_files": "policy_deployment_file",
    "policy_deployments": "policy_deployment",
    "policy_deployments_in_force": "policy_deployment_in_force",
    "pull_request_snapshots": "pull_request_snapshot",
    "repository_associations": "repository_association",
    "repository_layer_boundaries": "repository_layer_boundary",
    "repository_judged_policies": "repository_judged_policy",
    "repository_dispatched_processes": "repository_dispatched_process",
    "spend_bindings": "spend_binding",
}

#: The indexes whose names carry a table's.
INDEXES = {
    "repository_associations_origin_idx": "repository_association_origin_idx",
}

# Renames every constraint of the table whose name begins with the old
# table name, and names the primary key for the new table whatever it
# was called before. A DO block takes no parameters, so the names are
# written into it; they are the identifiers above, not input.
_RENAME_CONSTRAINTS = """
DO $$
DECLARE
    found record;
    renamed text;
BEGIN
    FOR found IN
        SELECT conname, contype
        FROM pg_constraint
        WHERE conrelid = '{table}'::regclass
    LOOP
        IF found.contype = 'p' THEN
            renamed := '{new}_pkey';
        ELSIF found.conname LIKE '{old}\\_%' THEN
            renamed := '{new}' || substr(found.conname, {after});
        ELSE
            CONTINUE;
        END IF;
        IF renamed <> found.conname THEN
            EXECUTE 'ALTER TABLE ' || quote_ident('{table}')
                || ' RENAME CONSTRAINT ' || quote_ident(found.conname)
                || ' TO ' || quote_ident(renamed);
        END IF;
    END LOOP;
END
$$
"""


def _rename(old: str, new: str) -> None:
    op.rename_table(old, new)
    op.execute(
        _RENAME_CONSTRAINTS.format(
            table=new, old=old, new=new, after=len(old) + 1
        )
    )


def upgrade() -> None:
    for old, new in RENAMED.items():
        _rename(old, new)
    for old, new in INDEXES.items():
        op.execute(f"ALTER INDEX {old} RENAME TO {new}")


def downgrade() -> None:
    for old, new in INDEXES.items():
        op.execute(f"ALTER INDEX {new} RENAME TO {old}")
    for old, new in RENAMED.items():
        _rename(new, old)
