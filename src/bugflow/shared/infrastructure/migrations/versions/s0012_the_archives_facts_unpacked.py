"""Unpack the archive's three facts into tables named for what one row
is (ADR 007), the first journal to be unpacked.

Creates archive_seal and archive_seal_claim for archive.sealed,
archive_registration and archive_registration_beside for
archive.bound, and archive_refusal for archive.refused, each keyed by
the event's id to the archive journal, and fills them from every row
there. The script stops before it writes if any row's payload has a key
the inventory of 24 October 2026 did not find, or lacks one it found on
every row, so no fact is unpacked by guess. The payload column stays,
as the record says, until the journal's last type is unpacked, which
for the archive is this script; it goes by a script of its own.

The downgrade drops the five tables.
"""

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0012"
down_revision = "0011"

#: What each fact's payload holds: the keys every row has, and the keys
#: some rows have. A key outside both stops the script.
REQUIRED = {
    "archive.sealed": (
        "ledger_id",
        "scope",
        "name",
        "head",
        "events",
        "files",
        "bytes",
        "caller",
        "client",
        "claims",
    ),
    "archive.bound": ("ledger_id", "scope", "beside"),
    "archive.refused": (
        "ledger_id",
        "scope",
        "name",
        "kind",
        "caller",
        "client",
    ),
}
OPTIONAL = {
    "archive.sealed": ("root",),
    "archive.bound": ("replaces",),
    "archive.refused": (),
}


def _event_id(references: str) -> sa.Column[Any]:
    return sa.Column(
        "event_id",
        PG_UUID(as_uuid=True),
        sa.ForeignKey(f"{references}.event_id"),
        primary_key=True,
    )


def _check_shapes() -> None:
    bind = op.get_bind()
    for event_type, required in REQUIRED.items():
        known = set(required) | set(OPTIONAL[event_type])
        scalars = bind.execute(
            sa.text(
                "SELECT count(*) FROM archive_journal WHERE event_type = :t "
                "AND jsonb_typeof(payload) <> 'object'"
            ),
            {"t": event_type},
        ).scalar_one()
        if scalars:
            raise RuntimeError(
                f"{scalars} {event_type} rows carry a payload that is not an "
                "object; read them before unpacking"
            )
        found = (
            bind.execute(
                sa.text(
                    "SELECT DISTINCT k FROM (SELECT payload "
                    "FROM archive_journal WHERE event_type = :t) r, "
                    "jsonb_object_keys(r.payload) k"
                ),
                {"t": event_type},
            )
            .scalars()
            .all()
        )
        unknown = sorted(set(found) - known)
        if unknown:
            raise RuntimeError(
                f"{event_type} rows carry keys the inventory did not find: "
                f"{unknown}; read them before unpacking"
            )
        for key in required:
            missing = bind.execute(
                sa.text(
                    "SELECT count(*) FROM archive_journal "
                    "WHERE event_type = :t AND NOT payload ? :k"
                ),
                {"t": event_type, "k": key},
            ).scalar_one()
            if missing:
                raise RuntimeError(
                    f"{missing} {event_type} rows lack {key!r}, which every "
                    "row had at the inventory; read them before unpacking"
                )


def upgrade() -> None:
    _check_shapes()
    op.create_table(
        "archive_seal",
        _event_id("archive_journal"),
        sa.Column("ledger_id", sa.Text, nullable=False),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("head", sa.Text, nullable=False),
        sa.Column("root", sa.Text),
        sa.Column("events", sa.Integer, nullable=False),
        sa.Column("files", sa.Integer, nullable=False),
        sa.Column("bytes", sa.BigInteger, nullable=False),
        sa.Column("caller", sa.Text, nullable=False),
        sa.Column("client", sa.Text, nullable=False),
    )
    op.create_index("archive_seal_ledger_idx", "archive_seal", ["ledger_id"])
    op.create_table(
        "archive_seal_claim",
        _event_id("archive_seal"),
        sa.Column("claim", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )
    op.create_table(
        "archive_registration",
        _event_id("archive_journal"),
        sa.Column("ledger_id", sa.Text, nullable=False),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("replaces_forge", sa.Text),
        sa.Column("replaces_repo", sa.Text),
        sa.Column("replaces_scope", sa.Text),
        sa.Column("replaces_origin", sa.Text),
    )
    op.create_index(
        "archive_registration_ledger_idx",
        "archive_registration",
        ["ledger_id"],
    )
    op.create_table(
        "archive_registration_beside",
        _event_id("archive_registration"),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("ledger_id", sa.Text, nullable=False),
    )
    op.create_table(
        "archive_refusal",
        _event_id("archive_journal"),
        sa.Column("ledger_id", sa.Text, nullable=False),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("caller", sa.Text, nullable=False),
        sa.Column("client", sa.Text, nullable=False),
    )
    op.create_index(
        "archive_refusal_ledger_idx", "archive_refusal", ["ledger_id"]
    )

    op.execute(
        """
        INSERT INTO archive_seal (event_id, ledger_id, scope, name, head, root,
                                  events, files, bytes, caller, client)
        SELECT event_id, payload->>'ledger_id', payload->>'scope',
               payload->>'name', payload->>'head', payload->>'root',
               (payload->>'events')::integer, (payload->>'files')::integer,
               (payload->>'bytes')::bigint, payload->>'caller',
               payload->>'client'
        FROM archive_journal WHERE event_type = 'archive.sealed'
        """
    )
    op.execute(
        """
        INSERT INTO archive_seal_claim (event_id, claim, value)
        SELECT j.event_id, c.key,
               CASE WHEN jsonb_typeof(c.value) = 'string' THEN c.value #>> '{}'
                    ELSE c.value::text END
        FROM archive_journal j, jsonb_each(j.payload->'claims') c
        WHERE j.event_type = 'archive.sealed'
        """
    )
    op.execute(
        """
        INSERT INTO archive_registration (event_id, ledger_id, scope,
                                          replaces_forge, replaces_repo,
                                          replaces_scope, replaces_origin)
        SELECT event_id, payload->>'ledger_id', payload->>'scope',
               payload->'replaces'->>'forge', payload->'replaces'->>'repo',
               payload->'replaces'->>'scope', payload->'replaces'->>'origin'
        FROM archive_journal WHERE event_type = 'archive.bound'
        """
    )
    op.execute(
        """
        INSERT INTO archive_registration_beside (event_id, position, ledger_id)
        SELECT j.event_id, b.ordinality - 1, b.value #>> '{}'
        FROM archive_journal j,
             jsonb_array_elements(j.payload->'beside') WITH ORDINALITY b
        WHERE j.event_type = 'archive.bound'
        """
    )
    op.execute(
        """
        INSERT INTO archive_refusal (event_id, ledger_id, scope, name, kind,
                                     caller, client)
        SELECT event_id, payload->>'ledger_id', payload->>'scope',
               payload->>'name', payload->>'kind', payload->>'caller',
               payload->>'client'
        FROM archive_journal WHERE event_type = 'archive.refused'
        """
    )


def downgrade() -> None:
    for table in (
        "archive_refusal",
        "archive_registration_beside",
        "archive_registration",
        "archive_seal_claim",
        "archive_seal",
    ):
        op.drop_table(table)
