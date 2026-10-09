"""Interface: the reading operations of the remote archive protocol,
for the ledger named.

What a client of the protocol has of a kept archive: what is kept of
the ledger, each event's bytes, and the bytes a CID names. The keeping
port has these and more, so the keeper itself satisfies this port; so
would a client of a keeper elsewhere. The search index reads through
it and nothing else, so the index can be rebuilt from any keeper of
the ledger.
"""

from typing import Protocol

from bugflow.archive.domain.models.description import Description


class ArchiveReadingService(Protocol):
    def describe(self, ledger_id: str) -> Description:
        """What is kept of the ledger."""
        ...

    def event(self, ledger_id: str, number: int) -> bytes:
        """The bytes of the ledger's event of that number, as its file
        holds them. Refused as absent when there is none."""
        ...

    def read(self, ledger_id: str, cid: str, path: str) -> bytes:
        """The bytes the ledger enrols under the CID: a file, an event,
        or the file at ``path`` beneath a directory. Refused as absent
        when the ledger enrols nothing there, as erased when it did."""
        ...
