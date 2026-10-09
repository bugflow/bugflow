"""What is kept of a ledger, as the remote archive protocol describes it."""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class Description:
    ledger_id: str
    #: What names the ledger's last event, its hash or its CID, or None
    #: for a ledger with no event kept.
    head: str | None
    #: How many events are kept.
    events: int
    #: The root the last event recorded, or None.
    root: str | None
    #: The CIDs whose bytes were erased, sorted.
    erased: tuple[str, ...] = ()
    #: The versions of the protocol the keeper serves, ascending, and
    #: by version the date after which it may stop serving one.
    protocols: tuple[int, ...] = (1, 2)
    retiring: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True, kw_only=True)
class Appended:
    description: Description
    #: False when the event was already the ledger's event of that
    #: number, and appending it again changed nothing.
    appended: bool
