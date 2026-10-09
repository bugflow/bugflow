"""The request and response of ``SearchArchiveUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.archive.domain.models.search_hit import SearchHit
from bugflow.shared.domain.values.caller import Caller


class SearchArchiveRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ledger_id: str
    caller: Caller
    #: What to search for. How it is read depends on the mode.
    query: str
    #: One of the modes the server offers. None means ``literal``.
    mode: str | None = None
    #: The most results to return. None means the server's own limit.
    limit: int | None = None
    #: A CID to search inside. None means the whole ledger.
    within: str | None = None


class SearchArchiveResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    hits: tuple[SearchHit, ...]
