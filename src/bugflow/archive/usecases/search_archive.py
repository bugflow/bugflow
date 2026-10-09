"""Use case: search a ledger's files. This is the protocol's "search"
operation.

A search result shows text from a file, so searching needs the same
permission as reading.
"""

from bugflow.archive.domain.admission import reader
from bugflow.archive.domain.repositories.bindings import BindingRepository
from bugflow.archive.domain.services.archive_access import (
    ArchiveAccessService,
)
from bugflow.archive.domain.services.searching import ArchiveSearchService
from bugflow.archive.dtos.search_archive import (
    SearchArchiveRequest,
    SearchArchiveResponse,
)


class SearchArchiveUseCase:
    """Takes a ledger, a query and a caller allowed to read the ledger.
    Returns where the query was found.
    """

    def __init__(
        self,
        bindings: BindingRepository,
        access: ArchiveAccessService,
        searching: ArchiveSearchService,
    ) -> None:
        self._bindings = bindings
        self._access = access
        self._searching = searching

    @property
    def modes(self) -> tuple[str, ...]:
        """The search modes offered."""
        return self._searching.modes

    def execute(self, request: SearchArchiveRequest) -> SearchArchiveResponse:
        reader(self._access, self._bindings, request.caller, request.ledger_id)
        return SearchArchiveResponse(
            hits=tuple(
                self._searching.search(
                    request.ledger_id,
                    request.query,
                    request.mode,
                    request.limit,
                    request.within,
                )
            )
        )
