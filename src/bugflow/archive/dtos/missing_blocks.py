"""DTOs for MissingBlocksUseCase: what asks and what comes back."""

from pydantic import BaseModel, ConfigDict

from bugflow.shared.domain.values.caller import Caller


class MissingBlocksRequest(BaseModel):
    """Some CIDs a client means to put, from one who may append to the
    ledger."""

    model_config = ConfigDict(frozen=True)

    ledger_id: str
    caller: Caller
    cids: tuple[str, ...]


class MissingBlocksResponse(BaseModel):
    """Those of the CIDs asked after that no block is held for, in the
    order asked."""

    model_config = ConfigDict(frozen=True)

    missing: tuple[str, ...]
