"""Recording facts in the journal.

Every context appends its own facts and may ask whether one is already
recorded. Reading the journal back is not here: a context that needs to
declares an interface of its own for the question it asks.
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from bugflow.shared.domain.models.journal_entry import JournalEntry


class RecordingService(Protocol):
    def append(self, entries: Sequence[JournalEntry]) -> None:
        """Record entries. An entry whose event id is already recorded is
        ignored, which makes retried writes safe."""
        ...

    def has_event(self, event_id: UUID) -> bool: ...
