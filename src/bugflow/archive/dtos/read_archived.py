"""DTOs for ReadArchivedUseCase: what asks and what comes back."""

from pydantic import BaseModel, ConfigDict

from bugflow.shared.domain.values.caller import Caller


class ReadArchivedRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ledger_id: str
    caller: Caller
    #: What the ledger enrols: a file, an event, or a directory.
    cid: str
    #: The path of a file beneath a directory, or empty.
    path: str = ""


class ReadArchivedResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: bytes
