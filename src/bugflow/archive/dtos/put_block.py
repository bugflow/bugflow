"""The request and response of ``PutBlockUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.shared.domain.values.caller import Caller


class PutBlockRequest(BaseModel):
    """One block to store: the CID the client says it has, and its bytes. The
    bytes are untrusted, and are stored only if they hash to that CID.
    """

    model_config = ConfigDict(frozen=True)

    ledger_id: str
    caller: Caller
    cid: str
    data: bytes


class PutBlockResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: True if the store did not have the block before.
    new: bool
