"""The interface for writing to the journal.

Any context may write facts and ask whether a fact is already there.
Reading facts back is not part of this interface: a context that needs
to query the journal declares its own interface for the query.
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from bugflow.shared.domain.models.journal_entry import JournalEntry


class RecordingService(Protocol):
    def append(self, entries: Sequence[JournalEntry]) -> None:
        """Write the entries. An entry whose id is already in the journal
        is skipped. An explicit origin on a retry must match the retained
        association. New entries inherit an unambiguous origin within
        the same workflow run and repository scope. An append is atomic.
        """
        ...

    def has_event(self, event_id: UUID) -> bool:
        """Whether the journal has an entry with this id."""
        ...
