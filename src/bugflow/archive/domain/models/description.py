"""The description of a ledger: what the server currently stores of it. This
is what the protocol's "describe" operation answers.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class Description:
    ledger_id: str
    #: The name of the ledger's latest event (its hash or its CID), or
    #: None if no event is stored.
    head: str | None
    #: The number of events stored.
    events: int
    #: The root CID of the archive as the latest event recorded it, or
    #: None.
    root: str | None
    #: CIDs whose bytes have been deleted on request, sorted.
    erased: tuple[str, ...] = ()
    #: ``protocols`` is the protocol versions this server serves, in
    #: ascending order. ``retiring`` gives, for a version about to be
    #: dropped, the date after which it may be.
    protocols: tuple[int, ...] = (1, 2)
    retiring: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True, kw_only=True)
class Appended:
    description: Description
    #: False if this exact event was already stored at that number, so
    #: the append changed nothing.
    appended: bool
