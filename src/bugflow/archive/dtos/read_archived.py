"""The request and response of ``ReadArchivedUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.shared.domain.values.caller import Caller


class ReadArchivedRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ledger_id: str
    caller: Caller
    #: The CID of a file, an event or a directory in the ledger.
    cid: str
    #: When ``cid`` is a directory, the path of a file inside it.
    #: Otherwise empty.
    path: str = ""


class ReadArchivedResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: bytes
