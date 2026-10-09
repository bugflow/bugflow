"""A search index kept in memory, for tests.

It matches with Python: ``in`` for the literal mode and the ``re`` module
for regex. pyposlib's own search matches the same way.
"""

import re
from collections.abc import Sequence

from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.domain.models.indexed_file import (
    FoundLine,
    IndexedFile,
)


class InMemoryIndexedFiles:
    def __init__(self) -> None:
        self.files: dict[str, IndexedFile] = {}

    def indexed(self, cids: Sequence[str]) -> set[str]:
        return {cid for cid in cids if cid in self.files}

    def keep(self, file: IndexedFile) -> None:
        self.files.setdefault(file.cid, file)

    def find(
        self, cids: Sequence[str], query: str, mode: str, limit: int
    ) -> list[FoundLine]:
        if mode == "literal":

            def is_hit(line: str) -> bool:
                return query in line

        else:
            try:
                pattern = re.compile(query)
            except re.error as error:
                raise ArchiveRefusedError(
                    "request", f"Not a regular expression: {error}"
                ) from error

            def is_hit(line: str) -> bool:
                return pattern.search(line) is not None

        found: list[FoundLine] = []
        for position, cid in enumerate(cids):
            file = self.files.get(cid)
            for number, line in enumerate(file.lines or () if file else (), 1):
                if is_hit(line):
                    found.append(
                        FoundLine(position=position, number=number, text=line)
                    )
                    if len(found) == limit:
                        return found
        return found


class InMemoryIndexPositions:
    def __init__(self) -> None:
        self.positions: dict[str, int] = {}

    def position(self, ledger_id: str) -> int:
        return self.positions.get(ledger_id, 0)

    def advance(self, ledger_id: str, events: int) -> None:
        self.positions[ledger_id] = max(self.position(ledger_id), events)
