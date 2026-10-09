"""The interface for the keeper: the part that checks and stores what clients
send.

It has one method for each operation of the remote archive protocol.

An implementation must check everything a client sends and trust nothing:

- An event is stored only if it correctly follows the events already
  stored.
- A file or block is stored only if its bytes hash to the CID it was sent
  under.
- For an event in the current format (schema 3), every file the ledger
  refers to must be stored here, and the archive's root CID, worked out
  from the events, must equal the root the event records.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol

from bugflow.archive.domain.models.description import Appended, Description


class KeepingService(Protocol):
    def describe(self, ledger_id: str) -> Description:
        """What is currently stored of the ledger."""
        ...

    def event(self, ledger_id: str, number: int) -> bytes:
        """The bytes of event number ``number``, exactly as stored. Refuses as
        "absent" if there is no such event.
        """
        ...

    def held(self, ledger_id: str, cids: Sequence[str]) -> list[str]:
        """Which of ``cids`` the store has no block for, in the order given.
        Protocol version 2.
        """
        ...

    def put(self, ledger_id: str, cid: str, data: bytes) -> bool:
        """Store one block. Returns True if the store did not have it before.

        Refuses as "entry" if ``data`` does not hash to ``cid``, and as
        "size" if it is larger than one block. Protocol version 2.
        """
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
        """Check and store one event.

        ``name`` is the event's file name and ``data`` its bytes. ``files``
        are the files it adds, by CID; in protocol version 2 this is empty,
        because the blocks were uploaded first. ``claims`` is what the
        client says about where the event came from. ``caller`` is who sent
        it.

        ``following`` is for old ledgers whose first events do not carry a
        ledger id. Such an event is accepted only together with the events
        after it, up to one that does carry this ledger's id. Those later
        events are checked and not stored.

        Sending an event that is already stored at its number changes
        nothing. If any check fails, the request is refused and nothing is
        stored.
        """
        ...

    def read(self, ledger_id: str, cid: str, path: str) -> bytes:
        """The bytes stored under a CID in this ledger: a file, an event, or,
        with ``path``, a file inside a directory.

        Refuses as "absent" if the ledger has nothing there, and as
        "erased" if it did and the bytes were deleted on request.
        """
        ...
