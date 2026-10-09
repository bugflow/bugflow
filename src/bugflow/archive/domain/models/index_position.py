"""How far the search index has read a ledger.

A ledger is a numbered list of events that nothing is inserted into or
removed from, so what the index has read of it is one number: the
events whose files it has indexed. Catching up is reading the events
after that number, and no queue is needed to say what is new.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class IndexPosition:
    ledger_id: str
    #: How many of the ledger's events the index has read, from the
    #: first. 0 for a ledger it has not read.
    events: int

    def __post_init__(self) -> None:
        if self.events < 0:
            raise ValueError(
                f"events indexed counts from 0, not {self.events}"
            )


@dataclass(frozen=True, kw_only=True)
class CaughtUp:
    """What one catch-up of a ledger did."""

    ledger_id: str
    #: The ledger's events, all of them read.
    events: int
    #: How many files were read and indexed this time.
    files: int
