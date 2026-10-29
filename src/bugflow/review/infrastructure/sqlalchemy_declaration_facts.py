"""The typed rows of what an operator declared (ADR 007).

Each change to a boundary, a withholding share or an allowance is a fact
in the policy journal, and its typed row is one of these tables, which
``UNPACKERS`` writes in the envelope's transaction. The row says what
the declaration replaced, so the setting in force at any past moment
can be read back.

The table definitions mirror the script that creates them.
"""

from collections.abc import Callable, Mapping
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert

from bugflow.review.domain.facts import (
    ALLOWANCE_DECLARED,
    BOUNDARY_DECLARED,
    CADENCE_DECLARED,
    WITHHOLDING_DECLARED,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry

metadata = sa.MetaData()


def _event_id() -> sa.Column[UUID]:
    return sa.Column(
        "event_id",
        PG_UUID(as_uuid=True),
        sa.ForeignKey("policy_journal.event_id"),
        primary_key=True,
    )


boundary_declaration = sa.Table(
    "boundary_declaration",
    metadata,
    _event_id(),
    sa.Column("layer", sa.Text, nullable=False),
    # Null where it was withdrawn, and where there was none before.
    sa.Column("boundary", sa.Text),
    sa.Column("was", sa.Text),
    sa.Column("declared_by", sa.Text, nullable=False),
)

cadence_declaration = sa.Table(
    "cadence_declaration",
    metadata,
    _event_id(),
    sa.Column("cadence", sa.Text, nullable=False),
    sa.Column("boundary", sa.Text),
    sa.Column("was", sa.Text),
    sa.Column("declared_by", sa.Text, nullable=False),
)

withholding_declaration = sa.Table(
    "withholding_declaration",
    metadata,
    _event_id(),
    sa.Column("share", sa.Float, nullable=False),
    sa.Column("was", sa.Float),
    sa.Column("declared_by", sa.Text, nullable=False),
)

allowance_declaration = sa.Table(
    "allowance_declaration",
    metadata,
    _event_id(),
    # The scope beyond the envelope's forge and repository, empty for
    # any.
    sa.Column("owner", sa.Text, nullable=False),
    sa.Column("layer", sa.Text, nullable=False),
    sa.Column("agent_id", sa.Text, nullable=False),
    sa.Column("per", sa.Text, nullable=False),
    # Whether the scope holds the allowance after the change, and held
    # it before. A limit held and null is no limit.
    sa.Column("held", sa.Boolean, nullable=False),
    sa.Column("usd", sa.Float),
    sa.Column("turns", sa.Float),
    sa.Column("was_held", sa.Boolean, nullable=False),
    sa.Column("was_usd", sa.Float),
    sa.Column("was_turns", sa.Float),
    sa.Column("declared_by", sa.Text, nullable=False),
)


def _unpacker(
    table: sa.Table, *columns: str
) -> Callable[[sa.Connection, JournalEntry], None]:
    """Write the payload's fields of those names to the table, keyed by
    the event's id."""

    def unpack(connection: sa.Connection, entry: JournalEntry) -> None:
        connection.execute(
            insert(table)
            .values(
                event_id=entry.event_id,
                **{name: entry.payload.get(name) for name in columns},
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return unpack


Unpacker = Callable[[sa.Connection, JournalEntry], None]

#: What writes a declaration's typed row, by event type.
UNPACKERS: Mapping[str, Unpacker] = {
    BOUNDARY_DECLARED: _unpacker(
        boundary_declaration, "layer", "boundary", "was", "declared_by"
    ),
    CADENCE_DECLARED: _unpacker(
        cadence_declaration, "cadence", "boundary", "was", "declared_by"
    ),
    WITHHOLDING_DECLARED: _unpacker(
        withholding_declaration, "share", "was", "declared_by"
    ),
    ALLOWANCE_DECLARED: _unpacker(
        allowance_declaration,
        "owner",
        "layer",
        "agent_id",
        "per",
        "held",
        "usd",
        "turns",
        "was_held",
        "was_usd",
        "was_turns",
        "declared_by",
    ),
}
