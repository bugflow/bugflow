"""Use cases for an administrator's pages: listing registered ledgers, listing
a ledger's bundles and files, downloading a file, and searching.

These use cases do not check who is calling. They are for an application
that has already established that its user is an administrator allowed to
see every archive. The use cases that serve the protocol's clients check
each caller themselves.
"""

from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.domain.models.inventory import (
    REFERENCE,
    ArchiveInventory,
)
from bugflow.archive.domain.repositories.bindings import BindingRepository
from bugflow.archive.domain.services.archive_inventory import (
    ArchiveInventoryService,
)
from bugflow.archive.domain.services.keeping import KeepingService
from bugflow.archive.domain.services.searching import ArchiveSearchService
from bugflow.archive.dtos.browse_archives import (
    BrowseArchiveRequest,
    BrowseArchiveResponse,
    DownloadArchivedFileRequest,
    DownloadArchivedFileResponse,
    ListArchivesRequest,
    ListArchivesResponse,
    LocateArchivedReferenceRequest,
    LocateArchivedReferenceResponse,
    LocatedHit,
    SearchBoundArchiveRequest,
    SearchBoundArchiveResponse,
)


class ListArchivesUseCase:
    """List every registered ledger."""

    def __init__(self, bindings: BindingRepository) -> None:
        self._bindings = bindings

    def execute(self, request: ListArchivesRequest) -> ListArchivesResponse:
        return ListArchivesResponse(archives=tuple(self._bindings.bindings()))


class BrowseArchiveUseCase:
    """List a ledger's bundles, or the files of one bundle. A bundle is the
    set of files one event added.
    """

    def __init__(
        self, bindings: BindingRepository, inventory: ArchiveInventoryService
    ) -> None:
        self._bindings = bindings
        self._inventory = inventory

    def execute(self, request: BrowseArchiveRequest) -> BrowseArchiveResponse:
        binding = self._bindings.for_ledger(request.ledger_id)
        if binding is None:
            raise ArchiveRefusedError(
                "absent", "No archive is bound to this ledger"
            )
        inventory = self._inventory.inventory(request.ledger_id)
        if request.bundle_number is not None:
            bundle = next(
                (
                    bundle
                    for bundle in inventory.bundles
                    if bundle.number == request.bundle_number
                ),
                None,
            )
            if bundle is None:
                raise ArchiveRefusedError(
                    "absent", "No bundle is enrolled at this number"
                )
            inventory = ArchiveInventory(
                events=inventory.events,
                files=bundle.files,
                bundles=(bundle,),
                folded=inventory.folded,
            )
        return BrowseArchiveResponse(binding=binding, inventory=inventory)


class DownloadArchivedFileUseCase:
    """Return the bytes of the file at one exact path in a ledger."""

    def __init__(
        self, browse: BrowseArchiveUseCase, keeping: KeepingService
    ) -> None:
        self._browse = browse
        self._keeping = keeping

    def execute(
        self, request: DownloadArchivedFileRequest
    ) -> DownloadArchivedFileResponse:
        archive = self._browse.execute(
            BrowseArchiveRequest(
                ledger_id=request.ledger_id,
                bundle_number=request.bundle_number,
            )
        )
        found = next(
            (
                file
                for file in archive.inventory.files
                if file.path == request.path
            ),
            None,
        )
        if found is None:
            raise ArchiveRefusedError(
                "absent", "No file is enrolled at this path"
            )
        if found.cid is None:
            raise ArchiveRefusedError(
                "absent", "This legacy file has no content identifier"
            )
        return DownloadArchivedFileResponse(
            path=found.path,
            data=self._keeping.read(request.ledger_id, found.cid, ""),
        )


class LocateArchivedReferenceUseCase:
    """Find where in a ledger the file named by an ``ipfs://`` reference
    appears.
    """

    def __init__(self, browse: BrowseArchiveUseCase) -> None:
        self._browse = browse

    def execute(
        self, request: LocateArchivedReferenceRequest
    ) -> LocateArchivedReferenceResponse:
        archive = self._browse.execute(
            BrowseArchiveRequest(ledger_id=request.ledger_id)
        )
        if not request.reference.startswith(REFERENCE):
            raise ArchiveRefusedError(
                "request", f"A reference begins {REFERENCE}"
            )
        places = archive.inventory.enrolled_at(request.reference)
        if not places:
            raise ArchiveRefusedError(
                "absent", "No file is enrolled at this reference"
            )
        return LocateArchivedReferenceResponse(
            binding=archive.binding, places=places
        )


class SearchBoundArchiveUseCase:
    """Search a ledger as the protocol's search does, and add to each result
    where its file appears in the ledger.
    """

    def __init__(
        self, browse: BrowseArchiveUseCase, searching: ArchiveSearchService
    ) -> None:
        self._browse = browse
        self._searching = searching

    @property
    def modes(self) -> tuple[str, ...]:
        """The search modes offered."""
        return self._searching.modes

    def execute(
        self, request: SearchBoundArchiveRequest
    ) -> SearchBoundArchiveResponse:
        archive = self._browse.execute(
            BrowseArchiveRequest(ledger_id=request.ledger_id)
        )
        hits = self._searching.search(
            request.ledger_id,
            request.query,
            request.mode,
            request.limit,
            request.within,
        )
        return SearchBoundArchiveResponse(
            binding=archive.binding,
            hits=tuple(
                LocatedHit(
                    hit=hit, places=archive.inventory.enrolled_at(hit.ref)
                )
                for hit in hits
            ),
        )
