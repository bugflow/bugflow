"""Use case: store one block. This is the protocol's "put" operation, in
version 2.

The keeper checks that the bytes hash to the CID, and stores them. This use
case decides whether the caller may upload, and records the upload so that
a block no event ever refers to can be found later.

Nothing is written to the journal here. A block only matters once an event
refers to it, and the append that follows is what the journal records.
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
    """Takes a block, the CID it should have, and a caller allowed to append
    to the ledger. Stores it and returns whether it was new.
    """

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
