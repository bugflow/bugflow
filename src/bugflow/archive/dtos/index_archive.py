"""DTOs for IndexArchiveUseCase: what asks and what comes back."""

from pydantic import BaseModel, ConfigDict


class IndexArchiveRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ledger_id: str


class IndexArchiveResponse(BaseModel):
    """What the catch-up did: the ledger's events, all read, and how
    many files it indexed this time."""

    model_config = ConfigDict(frozen=True)

    ledger_id: str
    events: int
    files: int
