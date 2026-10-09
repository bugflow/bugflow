"""The request and response of ``MissingBlocksUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.shared.domain.values.caller import Caller


class MissingBlocksRequest(BaseModel):
    """A list of block CIDs a client intends to upload, to learn which the
    server lacks.
    """

    model_config = ConfigDict(frozen=True)

    ledger_id: str
    caller: Caller
    cids: tuple[str, ...]


class MissingBlocksResponse(BaseModel):
    """The CIDs from the request that the server has no block for, in the
    order they were given.
    """

    model_config = ConfigDict(frozen=True)

    missing: tuple[str, ...]
