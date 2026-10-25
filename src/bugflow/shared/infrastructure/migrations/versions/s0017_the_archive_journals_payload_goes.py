"""Drop the archive journal's payload column, the first journal whose
every type is unpacked (ADR 007).

The archive's three types have had tables of their own since 0012, and
nothing reads an archive fact's payload. This script makes the view
``journal`` read null for the archive journal's payload and drops the
column from the table. The view's columns and types are as they were,
so a view a deployment keeps over it, as PMI's real_journal is, stands.

The check stops on an archive row of a type the archive has no table
for, and on a row whose typed row is missing, so no fact loses its
payload before a table holds it.

The downgrade puts the column back, nullable and empty, and the view
reads it again. The typed tables hold the facts, and the journal's
triggers reject a change to a row that is written, so the column is not
filled.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0017"
down_revision = "0016"

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

#: The archive's types and the table each is unpacked into.
TABLES = {
    "archive.sealed": "archive_seal",
    "archive.bound": "archive_registration",
    "archive.refused": "archive_refusal",
}


def _stop(found: int, what: str) -> None:
    if found:
        raise RuntimeError(
            f"{found} archive_journal rows {what}; read them before the "
            "column goes"
        )


def _count(sql: str, **params: object) -> int:
    return int(op.get_bind().execute(sa.text(sql), params).scalar_one())


def _check_unpacked() -> None:
    _stop(
        _count(
            "SELECT count(*) FROM archive_journal "
            "WHERE event_type <> ALL(CAST(:known AS text[]))",
            known=sorted(TABLES),
        ),
        "are of a type the archive has no table for",
    )
    for event_type, table in TABLES.items():
        _stop(
            _count(
                "SELECT count(*) FROM archive_journal j "
                "WHERE j.event_type = :t AND NOT EXISTS "
                f"(SELECT 1 FROM {table} t WHERE t.event_id = j.event_id)",
                t=event_type,
            ),
            f"of type {event_type} have no row in {table}",
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
    op.execute(_view(without_payload=("archive",)))
    op.drop_column("archive_journal", "payload")


def downgrade() -> None:
    op.add_column(
        "archive_journal", sa.Column("payload", JSONB, nullable=True)
    )
    op.execute(_view(without_payload=()))
