"""Driven ports: bringing the search index up to a ledger's events.

The ledger is the queue. A catch-up reads the events the index has not
read, indexes the files they enrol, and records how far it got. It is
asked for on a schedule, for every bound ledger, and by an append, for
its ledger, so a fresh seal is searchable at once and a missed request
costs a delay and nothing else.
"""

from typing import Protocol

from bugflow.archive.domain.models.index_position import CaughtUp


class ArchiveIndexingService(Protocol):
    def catch_up(self, ledger_id: str) -> CaughtUp:
        """Read the ledger's events the index has not read and index the
        files they enrol, until the index is at the ledger's last
        event. Refused as the reading port refuses."""
        ...


class IndexingRequestService(Protocol):
    def request_catch_up(self, ledger_id: str) -> None:
        """Ask that the ledger's index catch up. An implementation may do
        it now or have it done; it never raises, since the schedule
        catches up whatever a request misses."""
        ...
