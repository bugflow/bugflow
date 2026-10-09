"""The interface for searching a ledger's files.

The operation is defined in section 12 of the remote archive protocol
(poslib's ``doc/remote-archive-protocol.txt``). Each result is a reference
to a file, a range of lines, and the text of those lines. In the
``literal`` and ``regex`` modes, results come in the archive's own order.
In a mode that ranks, they come best first.
"""

from typing import Protocol

from bugflow.archive.domain.models.search_hit import SearchHit


class ArchiveSearchService(Protocol):
    @property
    def modes(self) -> tuple[str, ...]:
        """The search modes offered. ``literal`` is always one of them."""
        ...

    def search(
        self,
        ledger_id: str,
        query: str,
        mode: str | None = None,
        limit: int | None = None,
        within: str | None = None,
    ) -> list[SearchHit]:
        """Search the ledger's files for ``query``.

        ``mode`` defaults to ``literal``. ``limit`` is the most results to
        return. ``within``, a CID, restricts the search to that file or
        directory.

        Refuses as "mode" for a mode not offered, as "absent" if ``within``
        is not in the ledger, and as "request" for a bad query or limit.
        """
        ...
