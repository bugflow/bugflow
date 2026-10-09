"""An event of a ledger, as this server keeps it.

A scope's ledger stays with the scope; what is kept here is a copy of
each event, so that what a client sends next can be verified against
the chain so far and the two copies can be compared. The
bytes are the ledger file's, untouched: an event's name is its hash or
its CID, and a byte changed would be another event.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, kw_only=True)
class KeptEvent:
    ledger_id: str
    #: The event's place in the ledger, counting from 1 without gaps.
    number: int
    #: The ledger file's name, its number and what names the event.
    name: str
    #: The ledger file's bytes.
    data: bytes
    #: What the client said of where the event came from: the
    #: repository, the commit, the scope. Its words, recorded as said
    #: and verified by nobody.
    claims: dict[str, str] = field(default_factory=dict)
    #: Who appended it, as the token said: the subject.
    caller: str = ""

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError(
                f"an event's number counts from 1, not {self.number}"
            )
