"""Interface: the keeping side of the remote archive protocol.

The operations a client's port has, for the ledger named: what is kept
of it, an event, which blocks are missing, a block put, an append, a
read. An implementation takes nothing on trust: an event is
kept only as the next of a valid chain, a file only under the CID its
bytes have, a block only under the CID it hashes to, and from a
ledger's first schema 3 event every file it enrols must be held, block
by block, and the ledger must fold to the root the event records.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol

from bugflow.archive.domain.models.description import Appended, Description


class KeepingService(Protocol):
    def describe(self, ledger_id: str) -> Description:
        """What is kept of the ledger."""
        ...

    def event(self, ledger_id: str, number: int) -> bytes:
        """The bytes of the ledger's event of that number, as its file
        holds them. Refused as absent when there is none."""
        ...

    def held(self, ledger_id: str, cids: Sequence[str]) -> list[str]:
        """Which of ``cids`` no block is held for, in their order.
        Version 2 of the protocol."""
        ...

    def put(self, ledger_id: str, cid: str, data: bytes) -> bool:
        """Hold the block ``cid`` names, ``data``; whether it was not held
        before. Refused as entry unless the bytes hash to the CID, as
        size beyond one block. Version 2 of the protocol."""
        ...

    def append(
        self,
        ledger_id: str,
        name: str,
        data: bytes,
        files: Mapping[str, bytes],
        claims: Mapping[str, str],
        caller: str,
        following: Sequence[tuple[str, bytes]] = (),
    ) -> Appended:
        """Keep the event of bytes ``data`` that the ledger file ``name``
        is, with ``files`` by their CIDs, the client's ``claims`` and who
        appended it. Under version 2 ``files`` is empty, the bytes having
        been put as blocks first. ``following`` is the ledger's later
        events, each a name and bytes in order: an event that names no
        ledger is kept
        only when they are valid next events that name this ledger, and
        none of them is kept with it. The same event again at its number
        changes nothing. Refused, with nothing kept, unless everything
        verifies."""
        ...

    def read(self, ledger_id: str, cid: str, path: str) -> bytes:
        """The bytes the ledger enrols under the CID: a file, an event,
        or the file at ``path`` beneath a directory. Refused as absent
        when the ledger enrols nothing there, as erased when it did."""
        ...
