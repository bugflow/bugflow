"""Interface: the file inventory recorded by a kept ledger."""

from typing import Protocol

from bugflow.archive.domain.models.inventory import ArchiveInventory


class ArchiveInventoryService(Protocol):
    def inventory(self, ledger_id: str) -> ArchiveInventory:
        """Fold the kept events into their enrolled files, ordered by path."""
        ...
