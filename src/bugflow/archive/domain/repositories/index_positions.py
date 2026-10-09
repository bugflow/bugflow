"""Interface: how far the search index has read each ledger."""

from typing import Protocol

from bugflow.archive.domain.models.index_position import IndexPosition
from bugflow.shared.domain.repositories.base import BaseRepository


class IndexPositionRepository(BaseRepository[IndexPosition], Protocol):
    def position(self, ledger_id: str) -> int:
        """How many of the ledger's events the index has read; 0 for a
        ledger it has not."""
        ...

    def advance(self, ledger_id: str, events: int) -> None:
        """Record that the ledger's first ``events`` events are read.
        A position never moves back: two catch-ups at once each record
        what they read, and the greater stands."""
        ...
