"""Administrative reads, reached only behind the site's role gate.

The gate admits readers of all archives and passes no person identity.
These use cases are not the corpus API's per-caller reads.
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
    """List every operator-bound archive for an admitted site reader."""

    def __init__(self, bindings: BindingRepository) -> None:
        self._bindings = bindings

    def execute(self, request: ListArchivesRequest) -> ListArchivesResponse:
        return ListArchivesResponse(archives=tuple(self._bindings.bindings()))


class BrowseArchiveUseCase:
    """List a bound archive's bundles, or one bundle's files."""

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
    """Read the bytes of one exact file path enrolled by a bound ledger."""

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
    """Find where a bound ledger enrols the file a reference names."""

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
    """Search a bound ledger as the remote archive protocol does, for an
    admitted site reader: the hits a client is answered, each with where
    its file is enrolled."""

    def __init__(
        self, browse: BrowseArchiveUseCase, searching: ArchiveSearchService
    ) -> None:
        self._browse = browse
        self._searching = searching

    @property
    def modes(self) -> tuple[str, ...]:
        """The modes searched in, as describe lists them to a client."""
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
