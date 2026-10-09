"""The interface for storing the records of block uploads."""

from typing import Protocol

from bugflow.archive.domain.models.block_put import BlockPut
from bugflow.shared.domain.repositories.base import BaseRepository


class BlockPutRepository(BaseRepository[BlockPut], Protocol):
    def record(self, put: BlockPut) -> None:
        """Record an upload. If the same block was uploaded to the same ledger
        before, update the time on the existing record and keep its note of
        whether the block was new.
        """
        ...

    def of_ledger(self, ledger_id: str) -> list[BlockPut]:
        """The uploads recorded for the ledger, sorted by CID."""
        ...
