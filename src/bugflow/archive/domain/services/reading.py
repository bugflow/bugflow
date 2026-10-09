"""The interface for reading a stored archive: the read-only operations of the
remote archive protocol.

The keeper has these methods too, so a keeper can be used wherever this
interface is asked for. So could a client that talks to a keeper on another
machine.

The search index reads archives only through this interface. That means the
index can be rebuilt from any keeper that stores the ledger.
"""

from typing import Protocol

from bugflow.archive.domain.models.description import Description


class ArchiveReadingService(Protocol):
    def describe(self, ledger_id: str) -> Description:
        """What is currently stored of the ledger."""
        ...

    def event(self, ledger_id: str, number: int) -> bytes:
        """The bytes of event number ``number``, exactly as stored. Refuses as
        "absent" if there is no such event.
        """
        ...

    def read(self, ledger_id: str, cid: str, path: str) -> bytes:
        """The bytes stored under a CID in this ledger: a file, an event, or,
        with ``path``, a file inside a directory.

        Refuses as "absent" if the ledger has nothing there, and as
        "erased" if it did and the bytes were deleted on request.
        """
        ...
