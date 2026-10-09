"""An indexing request that is carried out straight away, in the same thread,
instead of being handed to a worker.

It is for tests, where a search right after an append must find the new
files, and for a server run without a worker. A request is never allowed to
raise, so if the catch-up fails the failure is dropped; the next request or
the schedule tries again.
"""

from contextlib import suppress

from bugflow.archive.domain.services.indexing import ArchiveIndexingService


class ImmediateIndexing:
    def __init__(self, indexing: ArchiveIndexingService) -> None:
        self._indexing = indexing

    def request_catch_up(self, ledger_id: str) -> None:
        with suppress(Exception):
            self._indexing.catch_up(ledger_id)
