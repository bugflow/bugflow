"""The interface for storing how far the search index has got with each
ledger.
"""

from typing import Protocol

from bugflow.archive.domain.models.index_position import IndexPosition
from bugflow.shared.domain.repositories.base import BaseRepository


class IndexPositionRepository(BaseRepository[IndexPosition], Protocol):
    def position(self, ledger_id: str) -> int:
        """The number of the ledger's events the index has covered, or 0."""
        ...

    def advance(self, ledger_id: str, events: int) -> None:
        """Record that the index has covered the ledger's first ``events``
        events. The stored number never goes down: if two catch-ups run at
        once, the larger number is kept.
        """
        ...
