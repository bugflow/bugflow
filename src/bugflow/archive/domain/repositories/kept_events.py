"""The interface for storing ledger events."""

from typing import Protocol

from bugflow.archive.domain.models.kept_event import KeptEvent
from bugflow.shared.domain.repositories.base import BaseRepository


class EventTakenError(Exception):
    """The ledger already has an event with that number.

    This happens when two clients send an event at the same moment, or one
    sends twice. The first to arrive is stored. The other is refused; two
    events are never merged.
    """


class KeptEventRepository(BaseRepository[KeptEvent], Protocol):
    def of_ledger(self, ledger_id: str) -> list[KeptEvent]:
        """The ledger's events in order. Empty if it has none."""
        ...

    def add(self, event: KeptEvent) -> None:
        """Store the event. Raises ``EventTakenError`` if the ledger already
        has an event with that number. A stored event is never replaced.
        """
        ...
