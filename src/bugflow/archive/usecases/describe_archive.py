"""Use case: say what is stored of a ledger. This is the protocol's "describe"
operation.

A client asks before sending, to check that its copy of the ledger and the
server's agree, and after a failure, to see what it still has to send.
"""

from bugflow.archive.domain.admission import reader
from bugflow.archive.domain.repositories.bindings import BindingRepository
from bugflow.archive.domain.services.archive_access import (
    ArchiveAccessService,
)
from bugflow.archive.domain.services.keeping import KeepingService
from bugflow.archive.dtos.describe_archive import (
    DescribeArchiveRequest,
    DescribeArchiveResponse,
)


class DescribeArchiveUseCase:
    """Takes a ledger and a caller allowed to read it. Returns the name of its
    latest event, how many events are stored, the archive's root CID, and
    which CIDs have been deleted on request.
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

    def execute(
        self, request: DescribeArchiveRequest
    ) -> DescribeArchiveResponse:
        reader(self._access, self._bindings, request.caller, request.ledger_id)
        kept = self._keeping.describe(request.ledger_id)
        return DescribeArchiveResponse(
            ledger_id=kept.ledger_id,
            head=kept.head,
            events=kept.events,
            root=kept.root,
            erased=kept.erased,
            protocols=kept.protocols,
            retiring=kept.retiring,
        )
