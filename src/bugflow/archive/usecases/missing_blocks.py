"""Use case: say which blocks of some a client holds are not kept.

The remote archive protocol's held, version 2. A client about to seal
asks it before putting, and again when it resumes after an
interruption, so that it puts only what the keeper lacks. Asked by one
who may append to the ledger, as a put is the first half of an append.
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
    """Given some CIDs and a caller who may append to the ledger,
    answers with those no block is held for."""

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
