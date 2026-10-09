"""An event of a ledger, as stored on this server.

The ledger itself lives in the repository it belongs to. This server stores
a copy of each event. The copy is needed to check the next event a client
sends, since each event must follow the one before, and it lets the
server's copy be compared with the repository's.

The event's bytes are stored exactly as received. An event is named by a
hash of its bytes, so changing one byte would make it a different event.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, kw_only=True)
class KeptEvent:
    ledger_id: str
    #: The event's position in the ledger: 1, 2, 3 and so on.
    number: int
    #: The event's file name: its number, then its hash or CID.
    name: str
    #: The event file's bytes, exactly as received.
    data: bytes
    #: What the client said about where the event came from, such as
    #: the repository and the commit. Stored as given. The server does
    #: not check any of it.
    claims: dict[str, str] = field(default_factory=dict)
    #: Who sent it: the subject from the caller's token.
    caller: str = ""

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError(
                f"an event's number counts from 1, not {self.number}"
            )
