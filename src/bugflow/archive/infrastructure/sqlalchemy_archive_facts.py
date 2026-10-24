"""The archive's three facts, unpacked into tables named for what one row
is (ADR 007).

An ``archive.sealed`` row is a seal: an event checked and stored, with
the ledger's state after it and what the client claimed about where it
came from. The claims are an open set the client sends, so each is a
row of ``archive_seal_claim``. An ``archive.bound`` row is a
registration of a ledger with the server, with what it replaced and the
other ledgers beside it in its scope, each beside a row. An
``archive.refused`` row is a refusal, with its kind.

Each table is keyed by the event's id, a foreign key to the archive
journal, so a typed row has one envelope. ``UNPACKERS`` writes the typed
row from the envelope's payload in the envelope's transaction; the script
that made the tables filled them from the rows already there.
"""

from collections.abc import Callable, Mapping
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert

from bugflow.shared.domain.models.journal_entry import JournalEntry

metadata = sa.MetaData()


def _event_id() -> sa.Column[Any]:
    return sa.Column(
        "event_id",
        PG_UUID(as_uuid=True),
        sa.ForeignKey("archive_journal.event_id"),
        primary_key=True,
    )


archive_seal = sa.Table(
    "archive_seal",
    metadata,
    _event_id(),
    sa.Column("ledger_id", sa.Text, nullable=False),
    sa.Column("scope", sa.Text, nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("head", sa.Text, nullable=False),
    # The root of the ledger after the event, or null where the keeper
    # had none to give.
    sa.Column("root", sa.Text),
    sa.Column("events", sa.Integer, nullable=False),
    sa.Column("files", sa.Integer, nullable=False),
    sa.Column("bytes", sa.BigInteger, nullable=False),
    sa.Column("caller", sa.Text, nullable=False),
    sa.Column("client", sa.Text, nullable=False),
    sa.Index("archive_seal_ledger_idx", "ledger_id"),
)

archive_seal_claim = sa.Table(
    "archive_seal_claim",
    metadata,
    sa.Column(
        "event_id",
        PG_UUID(as_uuid=True),
        sa.ForeignKey("archive_seal.event_id"),
        primary_key=True,
    ),
    sa.Column("claim", sa.Text, primary_key=True),
    sa.Column("value", sa.Text, nullable=False),
)

archive_registration = sa.Table(
    "archive_registration",
    metadata,
    _event_id(),
    sa.Column("ledger_id", sa.Text, nullable=False),
    sa.Column("scope", sa.Text, nullable=False),
    # What the ledger was registered for before, where it was.
    sa.Column("replaces_forge", sa.Text),
    sa.Column("replaces_repo", sa.Text),
    sa.Column("replaces_scope", sa.Text),
    sa.Column("replaces_origin", sa.Text),
    sa.Index("archive_registration_ledger_idx", "ledger_id"),
)

archive_registration_beside = sa.Table(
    "archive_registration_beside",
    metadata,
    sa.Column(
        "event_id",
        PG_UUID(as_uuid=True),
        sa.ForeignKey("archive_registration.event_id"),
        primary_key=True,
    ),
    sa.Column("position", sa.Integer, primary_key=True),
    sa.Column("ledger_id", sa.Text, nullable=False),
)

archive_refusal = sa.Table(
    "archive_refusal",
    metadata,
    _event_id(),
    sa.Column("ledger_id", sa.Text, nullable=False),
    sa.Column("scope", sa.Text, nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("caller", sa.Text, nullable=False),
    sa.Column("client", sa.Text, nullable=False),
    sa.Index("archive_refusal_ledger_idx", "ledger_id"),
)


def _text(value: object) -> str:
    """A claim's value as text: a string as it is, anything else as JSON."""
    import json

    return (
        value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    )


def unpack_seal(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    connection.execute(
        insert(archive_seal)
        .values(
            event_id=entry.event_id,
            ledger_id=p["ledger_id"],
            scope=p["scope"],
            name=p["name"],
            head=p["head"],
            root=p.get("root"),
            events=p["events"],
            files=p["files"],
            bytes=p["bytes"],
            caller=p["caller"],
            client=p["client"],
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
    )
    for claim, value in sorted(dict(p.get("claims") or {}).items()):
        connection.execute(
            insert(archive_seal_claim)
            .values(event_id=entry.event_id, claim=claim, value=_text(value))
            .on_conflict_do_nothing()
        )


def unpack_registration(
    connection: sa.Connection, entry: JournalEntry
) -> None:
    p = entry.payload
    replaces = p.get("replaces") or {}
    connection.execute(
        insert(archive_registration)
        .values(
            event_id=entry.event_id,
            ledger_id=p["ledger_id"],
            scope=p["scope"],
            replaces_forge=replaces.get("forge"),
            replaces_repo=replaces.get("repo"),
            replaces_scope=replaces.get("scope"),
            replaces_origin=replaces.get("origin"),
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
    )
    for position, ledger_id in enumerate(p.get("beside") or []):
        connection.execute(
            insert(archive_registration_beside)
            .values(
                event_id=entry.event_id, position=position, ledger_id=ledger_id
            )
            .on_conflict_do_nothing()
        )


def unpack_refusal(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    connection.execute(
        insert(archive_refusal)
        .values(
            event_id=entry.event_id,
            ledger_id=p["ledger_id"],
            scope=p["scope"],
            name=p["name"],
            kind=p["kind"],
            caller=p["caller"],
            client=p["client"],
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
    )


Unpacker = Callable[[sa.Connection, JournalEntry], None]

#: What writes each archive fact's typed row, by event type.
UNPACKERS: Mapping[str, Unpacker] = {
    "archive.sealed": unpack_seal,
    "archive.bound": unpack_registration,
    "archive.refused": unpack_refusal,
}
