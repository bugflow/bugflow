"""Drop the stocktake journal's payload column, the fourth journal whose
every type is unpacked (ADR 007).

The stocktake's five types have had tables of their own since 0015, and
the readers of a stocktake fact's payload read those tables. A
deployment that places types of its own in this journal has given each
a table by a script of its own. This script makes the view ``journal``
read null for the stocktake journal's payload, as 0017, 0018 and 0019
made it read null for the archive's, the forge's and the review's, and
drops the column from the table. The view's columns and types are as
they were, so a view a deployment keeps over it, as PMI's real_journal
is, stands.

The check stops on a stocktake row that no table keyed to the stocktake
journal holds a row for, whichever script made the table, so no fact
loses its payload before a table holds it. The tables are found by
their foreign key to ``stocktake_journal.event_id``.

The downgrade puts the column back, nullable and empty, and the view
reads it again, the other three staying null. The typed tables hold the
facts, and the journal's triggers reject a change to a row that is
written, so the column is not filled.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0020"
down_revision = "0019"

#: The journals the view is over, in the view's order.
KINDS = ("archive", "forge", "review", "stocktake", "policy")

#: The view's columns, as 0011 made them.
COLUMNS = (
    "event_id",
    "occurred_at",
    "recorded_at",
    "event_type",
    "forge",
    "repo",
    "pr_number",
    "commit_sha",
    "corpus_version",
    "workflow_id",
    "run_id",
    "payload",
    "agent_id",
    "build",
    "policy_repository",
    "policy_commit",
    "policy_content",
    "pull_request_id",
    "workflow_run_id",
)

#: The tables keyed to the stocktake journal by the event's id: the
#: package's, and a deployment's own.
TYPED_TABLES = """
SELECT DISTINCT tc.table_name
  FROM information_schema.table_constraints tc
  JOIN information_schema.key_column_usage kcu
    ON kcu.constraint_name = tc.constraint_name
   AND kcu.constraint_schema = tc.constraint_schema
  JOIN information_schema.constraint_column_usage ccu
    ON ccu.constraint_name = tc.constraint_name
   AND ccu.constraint_schema = tc.constraint_schema
 WHERE tc.constraint_type = 'FOREIGN KEY'
   AND tc.table_schema = current_schema()
   AND ccu.table_name = 'stocktake_journal'
   AND ccu.column_name = 'event_id'
   AND kcu.column_name = 'event_id'
"""


def _typed_tables() -> list[str]:
    rows = op.get_bind().execute(sa.text(TYPED_TABLES)).scalars().all()
    return sorted(str(name) for name in rows)


def _check_unpacked() -> None:
    tables = _typed_tables()
    if not tables:
        raise RuntimeError("no table is keyed to stocktake_journal")
    held = " OR ".join(
        f"EXISTS (SELECT 1 FROM {table} t WHERE t.event_id = j.event_id)"
        for table in tables
    )
    missing = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT event_type, count(*) FROM stocktake_journal j "
                f"WHERE NOT ({held}) GROUP BY event_type ORDER BY event_type"
            )
        )
        .all()
    )
    if missing:
        found = ", ".join(f"{count} of type {kind}" for kind, count in missing)
        raise RuntimeError(
            f"stocktake_journal rows have no row in a table keyed to the "
            f"journal: {found}; read them before the column goes"
        )


def _view(without_payload: tuple[str, ...]) -> str:
    """The view over the journals, reading null for the payload of each
    journal named, so that the view's columns stay as they were."""
    selects = []
    for kind in KINDS:
        columns = ", ".join(
            "NULL::jsonb AS payload"
            if column == "payload" and kind in without_payload
            else column
            for column in COLUMNS
        )
        selects.append(f"SELECT {columns} FROM {kind}_journal")
    return "CREATE OR REPLACE VIEW journal AS " + " UNION ALL ".join(selects)


def upgrade() -> None:
    _check_unpacked()
    op.execute(
        _view(without_payload=("archive", "forge", "review", "stocktake"))
    )
    op.drop_column("stocktake_journal", "payload")


def downgrade() -> None:
    op.add_column(
        "stocktake_journal", sa.Column("payload", JSONB, nullable=True)
    )
    op.execute(_view(without_payload=("archive", "forge", "review")))
