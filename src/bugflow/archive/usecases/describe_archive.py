"""Use case: say what is kept of a ledger.

The remote archive protocol's describe. A client asks it before it
sends, to find whether its ledger and the one kept here agree, and
after a failure, to find what it has to catch up on.
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
    """Given a ledger and a caller who may read it, answers with its
    head, how many events are kept, its root and what was erased."""

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
