"""One search result.

A result quotes the archive exactly: reading the file at ``ref`` and taking
the lines given returns ``passage`` byte for byte. A result never contains
text the server wrote itself, such as a summary.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class SearchHit:
    #: A reference to the file: ``ipfs://{cid}/{path}``.
    ref: str
    #: The first and last line of the passage, counting from 1. Both
    #: lines are part of it.
    first_line: int
    last_line: int
    #: The text of those lines, joined by newlines, with no newline at
    #: the end.
    passage: str
    #: A relevance score, for search modes that rank results. Higher is
    #: better. Scores from different searches cannot be compared. None
    #: for the literal and regex modes, which do not rank.
    score: float | None = None
