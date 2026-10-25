"""The stocktake's five facts, unpacked into tables named for what one
row is (ADR 007).

A ``stocktake.taken`` row is one stocktake of a layer: the period it
covered, the two commits a review of it compares and how many pull
requests merged in it, each a row of its own. The latest for a layer is
the layer's mark.

A ``stocktake.dispatched`` row is a step of a stocktake review's
dispatch, named by ``step``: ``dispatched`` with the runner and the
runner's name for the work, and ``refused`` and ``unavailable`` with
the reason no run started.

A ``stocktake.reviewed`` row is a finished review of a range, with its
outcome, its cost and its write-up. A ``stocktake.found`` row is one
finding the review stated, with where it was found in the column
``location``, since the payload's name for it, ``where``, is a word of
SQL's. A ``stocktake.graded`` row is a grader's verdict on a write-up.

Each table is keyed by the event's id, a foreign key to the stocktake
journal. ``UNPACKERS`` writes the typed rows from the envelope's payload
in the envelope's transaction; the script that made the tables filled
them from the rows already there.
"""

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert

from bugflow.shared.domain.models.journal_entry import JournalEntry

metadata = sa.MetaData()


def _event_id(references: str = "stocktake_journal") -> sa.Column[Any]:
    return sa.Column(
        "event_id",
        PG_UUID(as_uuid=True),
        sa.ForeignKey(f"{references}.event_id"),
        primary_key=True,
    )


stocktake = sa.Table(
    "stocktake",
    metadata,
    _event_id(),
    sa.Column("layer", sa.Text, nullable=False),
    # The start of the period; null on a layer's first stocktake.
    sa.Column("since", sa.DateTime(timezone=True)),
    sa.Column("until", sa.DateTime(timezone=True), nullable=False),
    sa.Column("merged", sa.Integer, nullable=False),
    # Where the last stocktake got to, and the last merge since; null on
    # a first stocktake, on an old one that recorded no commit, and
    # where nothing merged.
    sa.Column("base_sha", sa.Text),
    sa.Column("head_sha", sa.Text),
    sa.Index("stocktake_layer_idx", "layer"),
)

stocktake_pull_request = sa.Table(
    "stocktake_pull_request",
    metadata,
    _event_id("stocktake"),
    sa.Column("position", sa.Integer, primary_key=True),
    sa.Column("pull_request", sa.Integer, nullable=False),
)

stocktake_dispatch = sa.Table(
    "stocktake_dispatch",
    metadata,
    _event_id(),
    sa.Column("layer", sa.Text, nullable=False),
    sa.Column("agent_id", sa.Text, nullable=False),
    sa.Column("base_sha", sa.Text),
    sa.Column("head_sha", sa.Text),
    sa.Column("step", sa.Text, nullable=False),
    # The runner and its name for the work, for a run that started. The
    # first dispatch, on 24 September 2026, recorded no runner.
    sa.Column("runner", sa.Text),
    sa.Column("remote_id", sa.Text),
    # Why no run started, for the steps that say so.
    sa.Column("reason", sa.Text),
    sa.Index("stocktake_dispatch_step_idx", "step"),
    sa.Index("stocktake_dispatch_remote_idx", "runner", "remote_id"),
)

stocktake_review = sa.Table(
    "stocktake_review",
    metadata,
    _event_id(),
    sa.Column("layer", sa.Text, nullable=False),
    sa.Column("agent_id", sa.Text, nullable=False),
    sa.Column("outcome", sa.Text, nullable=False),
    sa.Column("cost_usd", sa.Float),
    sa.Column("cost_seconds", sa.Float),
    sa.Column("detail", sa.Text, nullable=False),
    sa.Column("write_up", sa.Text, nullable=False),
)

stocktake_finding = sa.Table(
    "stocktake_finding",
    metadata,
    _event_id(),
    sa.Column("layer", sa.Text, nullable=False),
    sa.Column("agent_id", sa.Text, nullable=False),
    sa.Column("index", sa.Integer, nullable=False),
    sa.Column("location", sa.Text, nullable=False),
    sa.Column("quote", sa.Text, nullable=False),
    sa.Column("claim", sa.Text, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
)

stocktake_grade = sa.Table(
    "stocktake_grade",
    metadata,
    _event_id(),
    sa.Column("layer", sa.Text, nullable=False),
    sa.Column("agent_id", sa.Text, nullable=False),
    sa.Column("status", sa.Text),
    sa.Column("detail", sa.Text, nullable=False),
)


def _one(connection: sa.Connection, table: sa.Table, **row: object) -> None:
    connection.execute(insert(table).values(**row).on_conflict_do_nothing())


def _many(
    connection: sa.Connection,
    table: sa.Table,
    rows: Iterable[Mapping[str, object]],
) -> None:
    listed = list(rows)
    if listed:
        connection.execute(insert(table).on_conflict_do_nothing(), listed)


def _when(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def unpack_taken(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    _one(
        connection,
        stocktake,
        event_id=entry.event_id,
        layer=p["layer"],
        since=_when(p["since"]),
        until=_when(p["until"]),
        merged=p["merged"],
        base_sha=p["base_sha"],
        head_sha=p["head_sha"],
    )
    _many(
        connection,
        stocktake_pull_request,
        (
            {
                "event_id": entry.event_id,
                "position": position,
                "pull_request": number,
            }
            for position, number in enumerate(p["pull_requests"])
        ),
    )


def unpack_dispatch(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    _one(
        connection,
        stocktake_dispatch,
        event_id=entry.event_id,
        layer=p["layer"],
        agent_id=p["agent_id"],
        base_sha=p["base_sha"],
        head_sha=p["head_sha"],
        step=p["step"],
        runner=p.get("runner"),
        remote_id=p.get("remote_id"),
        reason=p.get("reason"),
    )


def unpack_reviewed(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    cost = p["cost"] or {}
    _one(
        connection,
        stocktake_review,
        event_id=entry.event_id,
        layer=p["layer"],
        agent_id=p["agent_id"],
        outcome=p["outcome"],
        cost_usd=cost.get("usd"),
        cost_seconds=cost.get("seconds"),
        detail=p["detail"],
        write_up=p["write_up"],
    )


def unpack_found(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    _one(
        connection,
        stocktake_finding,
        event_id=entry.event_id,
        layer=p["layer"],
        agent_id=p["agent_id"],
        index=p["index"],
        location=p["where"],
        quote=p["quote"],
        claim=p["claim"],
        kind=p["kind"],
    )


def unpack_graded(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    _one(
        connection,
        stocktake_grade,
        event_id=entry.event_id,
        layer=p["layer"],
        agent_id=p["agent_id"],
        status=p["status"],
        detail=p["detail"],
    )


Unpacker = Callable[[sa.Connection, JournalEntry], None]

#: What writes each stocktake type's rows, by event type.
UNPACKERS: Mapping[str, Unpacker] = {
    "stocktake.taken": unpack_taken,
    "stocktake.dispatched": unpack_dispatch,
    "stocktake.reviewed": unpack_reviewed,
    "stocktake.found": unpack_found,
    "stocktake.graded": unpack_graded,
}
