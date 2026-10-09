"""The interface for the search index's store of files, and for searching
them.
"""

from collections.abc import Sequence
from typing import Protocol

from bugflow.archive.domain.models.indexed_file import (
    FoundLine,
    IndexedFile,
)
from bugflow.shared.domain.repositories.base import BaseRepository


class IndexedFileRepository(BaseRepository[IndexedFile], Protocol):
    def indexed(self, cids: Sequence[str]) -> set[str]:
        """Which of ``cids`` are already in the index, text files or not."""
        ...

    def keep(self, file: IndexedFile) -> None:
        """Add the file to the index. A CID already in the index is left
        alone, since a CID always names the same content.
        """
        ...

    def find(
        self, cids: Sequence[str], query: str, mode: str, limit: int
    ) -> list[FoundLine]:
        """Search the files named by ``cids`` and return the matching lines.

        ``mode`` is ``literal`` or ``regex``. Results are ordered by the
        file's position in ``cids``, then by line number, and at most
        ``limit`` are returned. A CID listed twice is searched in both
        positions.

        Raises ``ArchiveRefusedError`` of kind "request" for a regular
        expression the store cannot run.
        """
        ...
