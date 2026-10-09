"""The requests and responses of the use cases behind an administrator's
archive pages.
"""

from pydantic import BaseModel, ConfigDict

from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.archive.domain.models.inventory import (
    ArchiveInventory,
    EnrolledPlace,
)
from bugflow.archive.domain.models.search_hit import SearchHit


class ListArchivesRequest(BaseModel):
    model_config = ConfigDict(frozen=True)


class ListArchivesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    archives: tuple[ArchiveBinding, ...]


class BrowseArchiveRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ledger_id: str
    bundle_number: int | None = None


class BrowseArchiveResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    binding: ArchiveBinding
    inventory: ArchiveInventory


class DownloadArchivedFileRequest(BrowseArchiveRequest):
    path: str


class DownloadArchivedFileResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    data: bytes


class LocateArchivedReferenceRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ledger_id: str
    #: A reference to a file: ``ipfs://{cid}/{path}``.
    reference: str


class LocateArchivedReferenceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    binding: ArchiveBinding
    #: Every place the file appears in the ledger, sorted by path.
    places: tuple[EnrolledPlace, ...]


class SearchBoundArchiveRequest(BaseModel):
    """A search of one registered ledger, with the same parameters as the
    protocol's search. It names no caller: see
    ``usecases/browse_archives.py``.
    """

    model_config = ConfigDict(frozen=True)

    ledger_id: str
    query: str
    mode: str | None = None
    limit: int | None = None
    within: str | None = None


class LocatedHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    hit: SearchHit
    #: Where the result's file appears in the ledger, so a page can
    #: link to its bundle.
    places: tuple[EnrolledPlace, ...]


class SearchBoundArchiveResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    binding: ArchiveBinding
    #: The results, in the order the protocol's search returns them.
    hits: tuple[LocatedHit, ...]
