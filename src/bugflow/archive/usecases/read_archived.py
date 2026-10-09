"""Use case: return the bytes stored under a CID in a ledger. This is the
protocol's "read" operation.

The CID may be a file's or an event's, or a directory's together with the
path of a file inside it. The bytes are other people's content. They are
returned as they are and never interpreted.
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
    """Takes a ledger, a CID, an optional path and a caller allowed to read
    the ledger. Returns the bytes.
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

    def execute(self, request: ReadArchivedRequest) -> ReadArchivedResponse:
        reader(self._access, self._bindings, request.caller, request.ledger_id)
        return ReadArchivedResponse(
            data=self._keeping.read(
                request.ledger_id, request.cid, request.path
            )
        )
