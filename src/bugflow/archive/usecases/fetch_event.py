"""Use case: return one stored event by its number. This is the protocol's
"event" operation.

A client whose copy of the ledger is behind the server's uses it to fetch
the events it is missing.
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
    """Takes a ledger, an event number and a caller allowed to read the
    ledger. Returns the event's bytes exactly as stored.
    """

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
