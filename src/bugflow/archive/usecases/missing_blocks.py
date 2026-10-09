"""Use case: say which of a list of blocks the server does not have. This is
the protocol's "held" operation, in version 2.

A client asks before uploading, and again when resuming an interrupted
upload, so that it uploads only what is missing. The caller must be allowed
to append, since uploading blocks is the first step of an append.
"""

from bugflow.archive.domain.admission import admitted
from bugflow.archive.domain.repositories.bindings import BindingRepository
from bugflow.archive.domain.services.archive_access import (
    ArchiveAccessService,
)
from bugflow.archive.domain.services.keeping import KeepingService
from bugflow.archive.dtos.missing_blocks import (
    MissingBlocksRequest,
    MissingBlocksResponse,
)


class MissingBlocksUseCase:
    """Takes a list of CIDs and a caller allowed to append to the ledger.
    Returns the CIDs the server has no block for.
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

    def execute(self, request: MissingBlocksRequest) -> MissingBlocksResponse:
        admitted(
            self._access.may_append(request.caller, request.ledger_id),
            self._bindings,
            request.ledger_id,
        )
        return MissingBlocksResponse(
            missing=tuple(
                self._keeping.held(request.ledger_id, list(request.cids))
            )
        )
