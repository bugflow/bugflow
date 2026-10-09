"""Use case: read what a kept ledger enrols, by its CID.

The remote archive protocol's read: a file, an event, or the file at a
path beneath a directory. What is read is what a scope sealed, content
from a repository under study, and is handed on as bytes and never
interpreted here.
"""

from bugflow.archive.domain.admission import reader
from bugflow.archive.domain.repositories.bindings import BindingRepository
from bugflow.archive.domain.services.archive_access import (
    ArchiveAccessService,
)
from bugflow.archive.domain.services.keeping import KeepingService
from bugflow.archive.dtos.read_archived import (
    ReadArchivedRequest,
    ReadArchivedResponse,
)


class ReadArchivedUseCase:
    """Given a ledger, a CID, a path and a caller who may read the
    ledger, answers with the bytes the ledger enrols there."""

    def __init__(
        self,
        bindings: BindingRepository,
        access: ArchiveAccessService,
        keeping: KeepingService,
    ) -> None:
        self._bindings = bindings
        self._access = access
        self._keeping = keeping

    def execute(self, request: ReadArchivedRequest) -> ReadArchivedResponse:
        reader(self._access, self._bindings, request.caller, request.ledger_id)
        return ReadArchivedResponse(
            data=self._keeping.read(
                request.ledger_id, request.cid, request.path
            )
        )
