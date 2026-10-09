"""Interface: the ledgers whose archives this server keeps."""

from typing import Protocol

from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.shared.domain.repositories.base import BaseRepository


class BindingRepository(BaseRepository[ArchiveBinding], Protocol):
    def for_ledger(self, ledger_id: str) -> ArchiveBinding | None:
        """The ledger's binding, or None for a ledger this server keeps
        nothing for, which is the default."""
        ...

    def bindings(self) -> list[ArchiveBinding]:
        """Every binding, by repository, scope and ledger."""
        ...

    def save(self, binding: ArchiveBinding) -> None:
        """Bind the ledger, replacing what it was bound to."""
        ...
