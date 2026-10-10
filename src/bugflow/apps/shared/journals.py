"""The journal, composed: where the facts go and which build is writing.

The build is a property of the process, not of any fact it records, so
it is read once, by the program, and handed to the journal's adapter to
stamp on every row. Every program that records a fact builds its
journal here rather than constructing the adapter itself, so no program
can be the one that forgets the build. A static test holds the code to
it.

A build is a full git sha or nothing. A branch name, a build number or
``latest`` in the column would read as authoritative and identify no
source tree, so a malformed value raises at startup instead of being
recorded.
"""

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from bugflow.forge.infrastructure.sqlalchemy_journal_queries import (
    SqlAlchemyJournalQueries,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal

#: What a deployment sets to the git sha of the tree its image was built
#: from. Unset locally and in tests, where there is no build to name.
BUILD_VARIABLE = "BUILD_SHA"

_SHA = re.compile(r"[0-9a-f]{40}\Z")


def build_sha(environ: Mapping[str, str]) -> str | None:
    """Return the build this process is, or None where nothing said.

    Raises ``ValueError`` if the value is not a full git sha.
    """
    value = environ.get(BUILD_VARIABLE, "").strip()
    if not value:
        return None
    if not _SHA.match(value):
        raise ValueError(f"{BUILD_VARIABLE} is not a full git sha: {value!r}")
    return value


def stamped_journal(database_url: str, build: str | None) -> SqlAlchemyJournal:
    """Return the Postgres journal, stamping ``build`` on every row it
    writes. ``build`` is what ``build_sha`` read."""
    return SqlAlchemyJournal(database_url, build=build)


class DeliveryJournal:
    """The journal as the receive-delivery use case takes it: the stamped
    journal for recording, and the forge's queries for the question of
    what was received since a time. One object, because the use case
    takes one."""

    def __init__(
        self, recording: SqlAlchemyJournal, queries: SqlAlchemyJournalQueries
    ) -> None:
        self._recording = recording
        self._queries = queries

    def append(self, entries: Sequence[JournalEntry]) -> None:
        self._recording.append(entries)

    def has_event(self, event_id: UUID) -> bool:
        return self._recording.has_event(event_id)

    def received_since(self, ref: PullRequestRef, since: datetime) -> bool:
        return self._queries.received_since(ref, since)


def delivery_journal(database_url: str, build: str | None) -> DeliveryJournal:
    """Return the journal the receive-delivery use case takes, over
    Postgres, stamping ``build`` on every row it writes."""
    return DeliveryJournal(
        stamped_journal(database_url, build),
        SqlAlchemyJournalQueries(database_url),
    )
