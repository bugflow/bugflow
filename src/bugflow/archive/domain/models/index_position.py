"""How far the search index has got with a ledger.

A ledger's events are numbered from 1 and only ever added at the end. So
one number says what the index has covered: the count of events whose files
it has indexed. To catch up, the index reads the events after that number.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class IndexPosition:
    ledger_id: str
    #: The number of the ledger's events the index has covered, counting
    #: from the first. 0 if it has covered none.
    events: int

    def __post_init__(self) -> None:
        if self.events < 0:
            raise ValueError(
                f"events indexed counts from 0, not {self.events}"
            )


@dataclass(frozen=True, kw_only=True)
class CaughtUp:
    """The result of bringing one ledger's index up to date."""

    ledger_id: str
    #: The number of events the ledger has, all now covered.
    events: int
    #: The number of files indexed in this catch-up.
    files: int
