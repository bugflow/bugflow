"""A file the search index has read, by the CID of its bytes.

A CID names content wherever it is kept, so a file is indexed once
however many ledgers enrol it and under whatever paths. What is kept of
it is its lines, where it is text; a file that is not UTF-8 is recorded
as read with no lines, so that it is not read again.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class IndexedFile:
    cid: str
    #: The file's lines as the protocol counts them: its bytes decoded
    #: as UTF-8 and split at LF, a terminator after the last line making
    #: no line of its own. None for a file that is not text.
    lines: tuple[str, ...] | None

    @property
    def is_text(self) -> bool:
        return self.lines is not None


@dataclass(frozen=True, kw_only=True)
class FoundLine:
    """One line the index found a query in."""

    #: Which of the files asked about, as an index into the list asked.
    position: int
    #: The line's number in the file, counting from 1.
    number: int
    text: str
