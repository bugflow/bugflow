"""The method context's one fact, unpacked into a table named for what
one row is (ADR 007).

A ``policies.deployed`` row is one deploy: a policy deployment stored
and put in force on this server. It names the deployment by its
repository, commit and content hash, counts its files, says who sent
it and names the deployment it replaced, which is null for the server's
first. The deployment itself is kept in ``policy_deployment``; this
table is the fact that it was put in force, each time it was.

The table is keyed by the event's id, a foreign key to the policy
journal. ``UNPACKERS`` writes the typed row from the envelope's payload
in the envelope's transaction; the script that made the table filled it
from the rows already there.
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
        sa.ForeignKey("policy_journal.event_id"),
        primary_key=True,
    )


policy_deploy = sa.Table(
    "policy_deploy",
    metadata,
    _event_id(),
    sa.Column("repository", sa.Text, nullable=False),
    sa.Column("commit", sa.Text, nullable=False),
    sa.Column("content_hash", sa.Text, nullable=False),
    sa.Column("files", sa.Integer, nullable=False),
    # The identity that sent the deployment, as the claim named it.
    sa.Column("sent_by", sa.Text, nullable=False),
    # The deployment in force before this one; null for the first.
    sa.Column("replaced_repository", sa.Text),
    sa.Column("replaced_commit", sa.Text),
    sa.Column("replaced_content_hash", sa.Text),
    sa.Index("policy_deploy_commit_idx", "repository", "commit"),
)


def unpack_deploy(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    replaced = p["replaced"] or {}
    connection.execute(
        insert(policy_deploy)
        .values(
            event_id=entry.event_id,
            repository=p["repository"],
            commit=p["commit"],
            content_hash=p["content_hash"],
            files=p["files"],
            sent_by=p["sent_by"],
            replaced_repository=replaced.get("repository"),
            replaced_commit=replaced.get("commit"),
            replaced_content_hash=replaced.get("content_hash"),
        )
        .on_conflict_do_nothing()
    )


Unpacker = Callable[[sa.Connection, JournalEntry], None]

#: What writes the method context's typed row, by event type.
UNPACKERS: Mapping[str, Unpacker] = {
    "policies.deployed": unpack_deploy,
}
