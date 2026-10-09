"""The blocks put ahead of their events, held in memory, for tests."""

from bugflow.archive.domain.models.block_put import BlockPut


class InMemoryBlockPuts:
    def __init__(self) -> None:
        self._puts: dict[tuple[str, str], BlockPut] = {}
        self.renewed: list[tuple[str, str]] = []

    def record(self, put: BlockPut) -> None:
        key = (put.ledger_id, put.cid)
        if key in self._puts:
            # The first put says whether the store lacked the block.
            self.renewed.append(key)
            return
        self._puts[key] = put

    def of_ledger(self, ledger_id: str) -> list[BlockPut]:
        return [
            self._puts[key]
            for key in sorted(self._puts)
            if key[0] == ledger_id
        ]
