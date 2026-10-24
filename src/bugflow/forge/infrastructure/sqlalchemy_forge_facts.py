"""The forge's seven facts, unpacked into tables named for what one row
is (ADR 007).

A ``delivery.received`` row is a delivery: what the forge sent and what
was done with it. A ``webhook.reconciled`` row is a reconciliation of
one repository's webhook, with the events it listens for, each an event
row. A ``pr.observed`` row is an observation of a pull request: the
snapshot taken, the corpus and the installed agents it was taken under,
each a row, the deliveries it answered, the policies it was reviewed
for and the policies the server held, each a policy row with its
standing, and the commits as git recorded them, each a commit row. A
``pr.closed`` row is a closure, with the findings still outstanding as
rows. A ``pr.merged`` row is a merge. A ``reaction.recorded`` row is a
reaction to a comment, with the agents that had a part in the comment
as rows. A ``finding.dismissed`` row is a dismissal.

An observation written before 26 September 2026 recorded no scope, and
one written before 23 September 2026 no installed agents, so such a
row has no policy rows or no agent rows; its date says which.

The identifiers a payload carries, a login on the forge or a name and
an email address in a commit, are columns, as plain facts. What they
mean is for whoever analyses the journal, and the matching of
identifiers into identities comes later.

Each table is keyed by the event's id, a foreign key to the forge
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


def _event_id(references: str = "forge_journal") -> sa.Column[Any]:
    return sa.Column(
        "event_id",
        PG_UUID(as_uuid=True),
        sa.ForeignKey(f"{references}.event_id"),
        primary_key=True,
    )


delivery = sa.Table(
    "delivery",
    metadata,
    _event_id(),
    sa.Column("delivery_id", sa.Text, nullable=False),
    sa.Column("event", sa.Text, nullable=False),
    # The forge's action within the event, where the event has one.
    sa.Column("action", sa.Text),
    sa.Column("outcome", sa.Text, nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Index("delivery_delivery_id_idx", "delivery_id"),
)

webhook_reconciliation = sa.Table(
    "webhook_reconciliation",
    metadata,
    _event_id(),
    sa.Column("url", sa.Text, nullable=False),
    sa.Column("outcome", sa.Text, nullable=False),
    sa.Column("detail", sa.Text, nullable=False),
)

webhook_reconciliation_event = sa.Table(
    "webhook_reconciliation_event",
    metadata,
    _event_id("webhook_reconciliation"),
    sa.Column("event", sa.Text, primary_key=True),
)

pull_request_observation = sa.Table(
    "pull_request_observation",
    metadata,
    _event_id(),
    sa.Column("snapshot_id", sa.Text, nullable=False),
    # The most recent delivery the observation answered, where one did.
    sa.Column("delivery_id", sa.Text),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("head_branch", sa.Text, nullable=False),
    sa.Column("base_branch", sa.Text, nullable=False),
    sa.Column("author_login", sa.Text, nullable=False),
    sa.Column("file_count", sa.Integer, nullable=False),
    sa.Column("changed_lines", sa.Integer, nullable=False),
    sa.Index("pull_request_observation_snapshot_idx", "snapshot_id"),
)

pull_request_observation_delivery = sa.Table(
    "pull_request_observation_delivery",
    metadata,
    _event_id("pull_request_observation"),
    sa.Column("position", sa.Integer, primary_key=True),
    sa.Column("delivery_id", sa.Text, nullable=False),
)

#: A component of the corpus the observation was taken under, by name
#: and version.
pull_request_observation_component = sa.Table(
    "pull_request_observation_component",
    metadata,
    _event_id("pull_request_observation"),
    sa.Column("component", sa.Text, primary_key=True),
    sa.Column("version", sa.Text, nullable=False),
)

#: A review agent installed when the observation was taken, by name and
#: version.
pull_request_observation_agent = sa.Table(
    "pull_request_observation_agent",
    metadata,
    _event_id("pull_request_observation"),
    sa.Column("agent", sa.Text, primary_key=True),
    sa.Column("version", sa.Text, nullable=False),
)

#: A policy's standing for the observation: ``reviewed_for``, a policy
#: the pull request was reviewed for, or ``held``, a policy the server
#: could have applied. One held and not reviewed for was switched off
#: for the repository.
pull_request_observation_policy = sa.Table(
    "pull_request_observation_policy",
    metadata,
    _event_id("pull_request_observation"),
    sa.Column("standing", sa.Text, primary_key=True),
    sa.Column("policy_id", sa.Text, primary_key=True),
)

pull_request_observation_commit = sa.Table(
    "pull_request_observation_commit",
    metadata,
    _event_id("pull_request_observation"),
    sa.Column("position", sa.Integer, primary_key=True),
    sa.Column("sha", sa.Text, nullable=False),
    sa.Column("author_name", sa.Text, nullable=False),
    sa.Column("author_email", sa.Text, nullable=False),
    sa.Column("author_login", sa.Text, nullable=False),
    sa.Column("committer_name", sa.Text, nullable=False),
    sa.Column("committer_email", sa.Text, nullable=False),
    sa.Column("committer_login", sa.Text, nullable=False),
    sa.Column("verified", sa.Boolean, nullable=False),
    sa.Column("verification_reason", sa.Text, nullable=False),
)

pull_request_closure = sa.Table(
    "pull_request_closure",
    metadata,
    _event_id(),
    sa.Column("merged", sa.Boolean, nullable=False),
    # How many reactions to the review's comments were recorded at the
    # close.
    sa.Column("reactions", sa.Integer, nullable=False),
)

pull_request_closure_outstanding = sa.Table(
    "pull_request_closure_outstanding",
    metadata,
    _event_id("pull_request_closure"),
    sa.Column("position", sa.Integer, primary_key=True),
    sa.Column("policy_id", sa.Text, nullable=False),
    sa.Column("clause", sa.Text, nullable=False),
    sa.Column("subject", sa.Text, nullable=False),
)

pull_request_merge = sa.Table(
    "pull_request_merge",
    metadata,
    _event_id(),
    sa.Column("delivery_id", sa.Text, nullable=False),
)

reaction = sa.Table(
    "reaction",
    metadata,
    _event_id(),
    sa.Column("comment_id", sa.BigInteger, nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("login", sa.Text, nullable=False),
    sa.Column("reacted_at", sa.DateTime(timezone=True)),
    # The one agent whose part earned the reaction, where one agent
    # wrote the whole comment.
    sa.Column("agent_id", sa.Text),
    sa.Column("evaluated_in", sa.Text, nullable=False),
)

reaction_agent = sa.Table(
    "reaction_agent",
    metadata,
    _event_id("reaction"),
    sa.Column("position", sa.Integer, primary_key=True),
    sa.Column("agent_id", sa.Text, nullable=False),
)

finding_dismissal = sa.Table(
    "finding_dismissal",
    metadata,
    _event_id(),
    sa.Column("policy_id", sa.Text, nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("actor", sa.Text),
    sa.Column("comment_id", sa.BigInteger, nullable=False),
    sa.Column("delivery_id", sa.Text, nullable=False),
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


def unpack_delivery(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    _one(
        connection,
        delivery,
        event_id=entry.event_id,
        delivery_id=p["delivery_id"],
        event=p["event"],
        action=p.get("action"),
        outcome=p["outcome"],
        reason=p["reason"],
    )


def unpack_webhook_reconciliation(
    connection: sa.Connection, entry: JournalEntry
) -> None:
    p = entry.payload
    _one(
        connection,
        webhook_reconciliation,
        event_id=entry.event_id,
        url=p["url"],
        outcome=p["outcome"],
        detail=p["detail"],
    )
    _many(
        connection,
        webhook_reconciliation_event,
        ({"event_id": entry.event_id, "event": e} for e in p["events"]),
    )


def unpack_observation(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    _one(
        connection,
        pull_request_observation,
        event_id=entry.event_id,
        snapshot_id=p["snapshot_id"],
        delivery_id=p.get("delivery_id"),
        title=p["title"],
        head_branch=p["head_branch"],
        base_branch=p["base_branch"],
        author_login=p["author_login"],
        file_count=p["file_count"],
        changed_lines=p["changed_lines"],
    )
    _many(
        connection,
        pull_request_observation_delivery,
        (
            {"event_id": entry.event_id, "position": i, "delivery_id": d}
            for i, d in enumerate(p["delivery_ids"])
        ),
    )
    _many(
        connection,
        pull_request_observation_component,
        (
            {"event_id": entry.event_id, "component": k, "version": v}
            for k, v in sorted(dict(p["corpus"]).items())
        ),
    )
    _many(
        connection,
        pull_request_observation_agent,
        (
            {"event_id": entry.event_id, "agent": k, "version": v}
            for k, v in sorted(dict(p.get("installed") or {}).items())
        ),
    )
    _many(
        connection,
        pull_request_observation_policy,
        (
            {"event_id": entry.event_id, "standing": standing, "policy_id": i}
            for standing in ("reviewed_for", "held")
            for i in p.get(standing) or ()
        ),
    )
    _many(
        connection,
        pull_request_observation_commit,
        (
            {
                "event_id": entry.event_id,
                "position": i,
                "sha": c["sha"],
                "author_name": c["author_name"],
                "author_email": c["author_email"],
                "author_login": c["author_login"],
                "committer_name": c["committer_name"],
                "committer_email": c["committer_email"],
                "committer_login": c["committer_login"],
                "verified": c["verified"],
                "verification_reason": c["verification_reason"],
            }
            for i, c in enumerate(p["commits"])
        ),
    )


def unpack_closure(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    _one(
        connection,
        pull_request_closure,
        event_id=entry.event_id,
        merged=p["merged"],
        reactions=p["reactions"],
    )
    _many(
        connection,
        pull_request_closure_outstanding,
        (
            {
                "event_id": entry.event_id,
                "position": i,
                "policy_id": f["policy_id"],
                "clause": f["clause"],
                "subject": f["subject"],
            }
            for i, f in enumerate(p["outstanding"])
        ),
    )


def unpack_merge(connection: sa.Connection, entry: JournalEntry) -> None:
    _one(
        connection,
        pull_request_merge,
        event_id=entry.event_id,
        delivery_id=entry.payload["delivery_id"],
    )


def unpack_reaction(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    reacted_at = p.get("reacted_at")
    _one(
        connection,
        reaction,
        event_id=entry.event_id,
        comment_id=p["comment_id"],
        content=p["content"],
        login=p["login"],
        reacted_at=(
            datetime.fromisoformat(reacted_at)
            if isinstance(reacted_at, str)
            else None
        ),
        agent_id=p.get("agent_id"),
        evaluated_in=p["evaluated_in"],
    )
    _many(
        connection,
        reaction_agent,
        (
            {"event_id": entry.event_id, "position": i, "agent_id": a}
            for i, a in enumerate(p["agents"])
        ),
    )


def unpack_dismissal(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    _one(
        connection,
        finding_dismissal,
        event_id=entry.event_id,
        policy_id=p["policy_id"],
        reason=p["reason"],
        actor=p.get("actor"),
        comment_id=p["comment_id"],
        delivery_id=p["delivery_id"],
    )


Unpacker = Callable[[sa.Connection, JournalEntry], None]

#: What writes each forge fact's typed rows, by event type.
UNPACKERS: Mapping[str, Unpacker] = {
    "delivery.received": unpack_delivery,
    "webhook.reconciled": unpack_webhook_reconciliation,
    "pr.observed": unpack_observation,
    "pr.closed": unpack_closure,
    "pr.merged": unpack_merge,
    "reaction.recorded": unpack_reaction,
    "finding.dismissed": unpack_dismissal,
}
