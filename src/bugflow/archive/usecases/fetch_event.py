"""Use case: give one event of a kept ledger, by its number.

The remote archive protocol's event. A client behind what is kept here
fetches the events it lacks, verifies them as it verifies its own
ledger, and writes them.
"""

from bugflow.archive.domain.admission import reader
from bugflow.archive.domain.repositories.bindings import BindingRepository
from bugflow.archive.domain.services.archive_access import (
    ArchiveAccessService,
)
from bugflow.archive.domain.services.keeping import KeepingService
from bugflow.archive.dtos.fetch_event import (
    FetchEventRequest,
    FetchEventResponse,
)


class FetchEventUseCase:
    """Given a ledger, a number and a caller who may read the ledger,
    answers with the event's bytes as the ledger's file holds them."""

    def __init__(
        self,
        bindings: BindingRepository,
        access: ArchiveAccessService,
        keeping: KeepingService,
    ) -> None:
        self._bindings = bindings
        self._access = access
        self._keeping = keeping

    def execute(self, request: FetchEventRequest) -> FetchEventResponse:
        reader(self._access, self._bindings, request.caller, request.ledger_id)
        return FetchEventResponse(
            data=self._keeping.event(request.ledger_id, request.number)
        )
