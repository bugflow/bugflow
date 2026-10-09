"""Where a query was found in a kept archive, as the remote archive
protocol's search answers it.

A hit is the index's claim and the archive is the authority: reading
``ref`` at the range gives ``passage``, byte for byte, or the index is
wrong. A hit that composes text of its own is not one.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class SearchHit:
    #: The file, as a sealed item's links name it: ``ipfs://{cid}/{path}``.
    ref: str
    #: The lines of the file the passage is, counting from 1, both
    #: included.
    first_line: int
    last_line: int
    #: The file's text at those lines, joined by LF with no terminator
    #: after the last.
    passage: str
    #: In a ranked mode, higher being better, ordering one answer and
    #: nothing else. None in literal and regex.
    score: float | None = None
