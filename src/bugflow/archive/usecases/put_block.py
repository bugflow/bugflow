"""Use case: hold one block a client is about to enrol.

The remote archive protocol's put, version 2. The keeping port holds
the bytes to their CID and keeps them; this decides who may ask and
records the put, so that a block no event ever claims can be found by
the ledger it was put to and when. A block is not a fact against the
ledger's repository until an event enrols it, so nothing is journalled
here: the append that follows is.
"""

from bugflow.archive.domain.admission import admitted
from bugflow.archive.domain.models.block_put import BlockPut
from bugflow.archive.domain.repositories.bindings import BindingRepository
from bugflow.archive.domain.repositories.block_puts import (
    BlockPutRepository,
)
from bugflow.archive.domain.services.archive_access import (
    ArchiveAccessService,
)
from bugflow.archive.domain.services.keeping import KeepingService
from bugflow.archive.dtos.put_block import (
    PutBlockRequest,
    PutBlockResponse,
)


class PutBlockUseCase:
    """Given a block and the CID it claims to be, from a caller who may
    append to the ledger, holds it and answers whether it was new."""

    def __init__(
        self,
        bindings: BindingRepository,
        access: ArchiveAccessService,
        keeping: KeepingService,
        puts: BlockPutRepository,
    ) -> None:
        self._bindings = bindings
        self._access = access
        self._keeping = keeping
        self._puts = puts

    def execute(self, request: PutBlockRequest) -> PutBlockResponse:
        admitted(
            self._access.may_append(request.caller, request.ledger_id),
            self._bindings,
            request.ledger_id,
        )
        new = self._keeping.put(request.ledger_id, request.cid, request.data)
        self._puts.record(
            BlockPut(
                ledger_id=request.ledger_id,
                cid=request.cid,
                size=len(request.data),
                caller=request.caller.subject,
                new=new,
            )
        )
        return PutBlockResponse(new=new)
