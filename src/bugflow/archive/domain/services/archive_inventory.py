"""The interface for working out a ledger's inventory: the files its events
refer to.
"""

from typing import Protocol

from bugflow.archive.domain.models.inventory import ArchiveInventory


class ArchiveInventoryService(Protocol):
    def inventory(self, ledger_id: str) -> ArchiveInventory:
        """Read the ledger's stored events and return the files they refer to,
        sorted by path.
        """
        ...
