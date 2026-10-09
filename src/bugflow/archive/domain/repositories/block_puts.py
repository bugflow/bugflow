"""Interface: the blocks put to kept ledgers ahead of their events."""

from typing import Protocol

from bugflow.archive.domain.models.block_put import BlockPut
from bugflow.shared.domain.repositories.base import BaseRepository


class BlockPutRepository(BaseRepository[BlockPut], Protocol):
    def record(self, put: BlockPut) -> None:
        """Record the put. The same block put to the same ledger again
        renews the record's time and keeps whether it was new."""
        ...

    def of_ledger(self, ledger_id: str) -> list[BlockPut]:
        """The blocks put to the ledger, by CID in order."""
        ...
