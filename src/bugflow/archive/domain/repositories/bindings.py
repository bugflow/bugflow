"""The interface for storing bindings: the records of which ledgers this
server stores archives for.
"""

from typing import Protocol

from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.shared.domain.repositories.base import BaseRepository


class BindingRepository(BaseRepository[ArchiveBinding], Protocol):
    def for_ledger(self, ledger_id: str) -> ArchiveBinding | None:
        """The ledger's binding, or None if the ledger is not registered."""
        ...

    def bindings(self) -> list[ArchiveBinding]:
        """Every binding, sorted by repository, scope and ledger."""
        ...

    def save(self, binding: ArchiveBinding) -> None:
        """Register the ledger. If it is already registered, replace what it
        was registered for.
        """
        ...
