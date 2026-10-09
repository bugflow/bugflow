"""Use case: bring a ledger's search index up to date.

A worker runs it: on a schedule for every registered ledger, and for one
ledger after an append. It takes no caller, because it returns nothing to
anyone outside. A ledger that is not registered is refused as "absent".
"""

from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.domain.repositories.bindings import BindingRepository
from bugflow.archive.domain.services.indexing import ArchiveIndexingService
from bugflow.archive.dtos.index_archive import (
    IndexArchiveRequest,
    IndexArchiveResponse,
)


class IndexArchiveUseCase:
    """Takes a registered ledger. Indexes the events the index has not
    covered, and returns how far it got.
    """

    def __init__(
        self, bindings: BindingRepository, indexing: ArchiveIndexingService
    ) -> None:
        self._bindings = bindings
        self._indexing = indexing

    def execute(self, request: IndexArchiveRequest) -> IndexArchiveResponse:
        if self._bindings.for_ledger(request.ledger_id) is None:
            raise ArchiveRefusedError(
                "absent", f"No ledger {request.ledger_id} is kept"
            )
        caught = self._indexing.catch_up(request.ledger_id)
        return IndexArchiveResponse(
            ledger_id=caught.ledger_id,
            events=caught.events,
            files=caught.files,
        )
