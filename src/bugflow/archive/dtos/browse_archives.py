"""Requests and responses for the administrator's archive browser."""

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
    #: ``ipfs://{cid}/{path}``, as a sealed item's links and a search
    #: hit's ``ref`` name a file.
    reference: str


class LocateArchivedReferenceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    binding: ArchiveBinding
    #: Each place the reference's file is enrolled, in order of path.
    places: tuple[EnrolledPlace, ...]


class SearchBoundArchiveRequest(BaseModel):
    """The remote archive protocol's search parameters, for one bound
    ledger and no caller."""

    model_config = ConfigDict(frozen=True)

    ledger_id: str
    query: str
    mode: str | None = None
    limit: int | None = None
    within: str | None = None


class LocatedHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    hit: SearchHit
    #: Where the hit's file is enrolled, for a link to its bundle.
    places: tuple[EnrolledPlace, ...]


class SearchBoundArchiveResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    binding: ArchiveBinding
    #: The hits a client of the protocol is answered, in its order.
    hits: tuple[LocatedHit, ...]
