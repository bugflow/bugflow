"""Use case: bring a kept ledger's search index up to its events.

Run by the worker, for every bound ledger on a schedule and for one
after an append; no caller is asked after, since nothing is answered to
anyone. A ledger nobody bound is refused as absent: this server keeps,
and so indexes, an archive only where an operator said so.
"""

from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.domain.repositories.bindings import BindingRepository
from bugflow.archive.domain.services.indexing import ArchiveIndexingService
from bugflow.archive.dtos.index_archive import (
    IndexArchiveRequest,
    IndexArchiveResponse,
)


class IndexArchiveUseCase:
    """Given a bound ledger, reads the events its index has not read and
    answers with how far it got."""

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
