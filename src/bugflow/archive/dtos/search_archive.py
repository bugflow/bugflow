"""DTOs for SearchArchiveUseCase: what asks and what comes back."""

from pydantic import BaseModel, ConfigDict

from bugflow.archive.domain.models.search_hit import SearchHit
from bugflow.shared.domain.values.caller import Caller


class SearchArchiveRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ledger_id: str
    caller: Caller
    #: The query, as the mode reads it.
    query: str
    #: A mode describe lists, or None for literal.
    mode: str | None = None
    #: The most hits to answer with, or None for the keeper's own cap.
    limit: int | None = None
    #: A CID the ledger enrols, to search beneath, or None for all of it.
    within: str | None = None


class SearchArchiveResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    hits: tuple[SearchHit, ...]
