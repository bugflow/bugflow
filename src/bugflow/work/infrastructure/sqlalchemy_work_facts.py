"""The work context's one fact, unpacked into a table named for what one
row is (ADR 007).

A ``completion.received`` row is a completion a runner sent for a
checkout agent's run: which runner, the run's id there, and what was
done with it. The type is placed in the review journal, since it is
about a review's dispatch, and its table is keyed by the event's id, a
foreign key to that journal. ``UNPACKERS`` writes the typed row from the
envelope's payload in the envelope's transaction.
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
        sa.ForeignKey("review_journal.event_id"),
        primary_key=True,
    )


completion = sa.Table(
    "completion",
    metadata,
    _event_id(),
    sa.Column("runner", sa.Text, nullable=False),
    sa.Column("remote_id", sa.Text, nullable=False),
    sa.Column("outcome", sa.Text, nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Index("completion_remote_idx", "runner", "remote_id"),
)


def unpack_completion(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    connection.execute(
        insert(completion)
        .values(
            event_id=entry.event_id,
            runner=p["runner"],
            remote_id=p["remote_id"],
            outcome=p["outcome"],
            reason=p["reason"],
        )
        .on_conflict_do_nothing()
    )


Unpacker = Callable[[sa.Connection, JournalEntry], None]

#: What writes the work context's typed row, by event type.
UNPACKERS: Mapping[str, Unpacker] = {
    "completion.received": unpack_completion,
}
