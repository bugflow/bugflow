"""Interface: the files the search index has read, and where a query
is found in them."""

from collections.abc import Sequence
from typing import Protocol

from bugflow.archive.domain.models.indexed_file import (
    FoundLine,
    IndexedFile,
)
from bugflow.shared.domain.repositories.base import BaseRepository


class IndexedFileRepository(BaseRepository[IndexedFile], Protocol):
    def indexed(self, cids: Sequence[str]) -> set[str]:
        """Which of ``cids`` have been read, text or not."""
        ...

    def keep(self, file: IndexedFile) -> None:
        """Index the file. A CID already indexed is left as it was: the
        bytes a CID names do not change."""
        ...

    def find(
        self, cids: Sequence[str], query: str, mode: str, limit: int
    ) -> list[FoundLine]:
        """The lines of the files ``cids`` name that ``query`` hits in
        ``mode``, ``literal`` or ``regex``: in the order of ``cids``,
        then by line, the first ``limit`` of them. A CID given twice is
        searched at each position. Refused as request for an expression
        the store does not take."""
        ...
