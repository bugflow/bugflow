"""DTOs for PutBlockUseCase: what asks and what comes back."""

from pydantic import BaseModel, ConfigDict

from bugflow.shared.domain.values.caller import Caller


class PutBlockRequest(BaseModel):
    """One block of an item a client is about to seal: the CID it
    claims to be, and the bytes, which are content from a repository
    under study and are held to the CID before anything is kept."""

    model_config = ConfigDict(frozen=True)

    ledger_id: str
    caller: Caller
    cid: str
    data: bytes


class PutBlockResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: Whether the store lacked the block before this put.
    new: bool
