"""The request and response of ``IndexArchiveUseCase``."""

from pydantic import BaseModel, ConfigDict


class IndexArchiveRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ledger_id: str


class IndexArchiveResponse(BaseModel):
    """The result of a catch-up: how many events the ledger has, all now
    covered by the index, and how many files were indexed this time.
    """

    model_config = ConfigDict(frozen=True)

    ledger_id: str
    events: int
    files: int
