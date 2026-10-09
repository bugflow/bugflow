"""Use case: search what a kept ledger enrols.

The remote archive protocol's search, for a caller who may read the
ledger: a hit is a read of a passage, so it takes read's access and no
other. Where the hits come from is the search port's.
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
    """Given a ledger, a query and a caller who may read the ledger,
    answers with where the query is found."""

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
        """The modes searched in, for describe to list."""
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
