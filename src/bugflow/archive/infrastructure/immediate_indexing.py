"""A request to catch up answered at once, in the caller's thread.

For a host run with no scheduler, and for tests, where a search after
an append must see the event. The request port never raises, so a
catch-up that fails is dropped here, for the next request or the
schedule to make good.
"""

from contextlib import suppress

from bugflow.archive.domain.services.indexing import ArchiveIndexingService


class ImmediateIndexing:
    def __init__(self, indexing: ArchiveIndexingService) -> None:
        self._indexing = indexing

    def request_catch_up(self, ledger_id: str) -> None:
        with suppress(Exception):
            self._indexing.catch_up(ledger_id)
