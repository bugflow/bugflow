"""The interfaces for keeping the search index up to date.

Bringing a ledger's index up to date is called a catch-up. It reads the
events the index has not covered yet, indexes the files they add, and
records how far it got. No separate queue of work is needed: the ledger's
own event numbers say what is new.

A catch-up is asked for in two ways: on a schedule, for every registered
ledger, and straight after an append, for that ledger, so that new files
can be searched at once. If a request after an append is lost, the schedule
covers it later.
"""

from typing import Protocol

from bugflow.archive.domain.models.index_position import CaughtUp


class ArchiveIndexingService(Protocol):
    def catch_up(self, ledger_id: str) -> CaughtUp:
        """Bring the ledger's index up to its latest event. Raises
        ``ArchiveRefusedError`` if the ledger cannot be read.
        """
        ...


class IndexingRequestService(Protocol):
    def request_catch_up(self, ledger_id: str) -> None:
        """Ask for the ledger's index to be brought up to date. The work may
        be done now or handed to something else. This never raises: a
        request that fails is covered by the schedule.
        """
        ...
