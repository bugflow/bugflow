"""Interface: the search operation of the remote archive protocol,
for the ledger named.

Section 12 of poslib's ``doc/remote-archive-protocol.txt``: hits in the
archive's order in ``literal`` and ``regex``, in order of score in a
ranked mode, each a reference, a range and the passage there, which a
read at the reference gives byte for byte. How an implementation finds
them is its own.
"""

from typing import Protocol

from bugflow.archive.domain.models.search_hit import SearchHit


class ArchiveSearchService(Protocol):
    @property
    def modes(self) -> tuple[str, ...]:
        """The modes searched in, ``literal`` among them, as describe
        lists them."""
        ...

    def search(
        self,
        ledger_id: str,
        query: str,
        mode: str | None = None,
        limit: int | None = None,
        within: str | None = None,
    ) -> list[SearchHit]:
        """Where ``query`` is found in the files the ledger enrols: in
        ``literal`` where ``mode`` is None, at most ``limit`` hits, and
        beneath the CID ``within`` where it is given. Refused as mode
        for a mode not served, as absent for a ``within`` the ledger
        does not enrol, as request for a query or limit not as the
        protocol has them."""
        ...
