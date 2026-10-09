"""The request and response of ``FetchEventUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.shared.domain.values.caller import Caller


class FetchEventRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ledger_id: str
    caller: Caller
    #: The event's number in the ledger, counting from 1.
    number: int


class FetchEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: The event's bytes, exactly as stored.
    data: bytes
