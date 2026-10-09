"""A file in the search index.

A file is identified by its CID, which is a hash of its content. The same
content has the same CID in every ledger and under every path, so each
distinct file is indexed once.

For a text file the index stores its lines. A file that is not valid UTF-8
is recorded with no lines, so the index knows it has been looked at and
does not fetch it again.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class IndexedFile:
    cid: str
    #: The file's lines: its bytes decoded as UTF-8 and split at each
    #: newline. A newline at the very end does not add an empty last
    #: line. None for a file that is not text.
    lines: tuple[str, ...] | None

    @property
    def is_text(self) -> bool:
        return self.lines is not None


@dataclass(frozen=True, kw_only=True)
class FoundLine:
    """One line that matched a search."""

    #: Which file the line is in, as a position in the list of files
    #: that was searched.
    position: int
    #: The line number, counting from 1.
    number: int
    text: str
