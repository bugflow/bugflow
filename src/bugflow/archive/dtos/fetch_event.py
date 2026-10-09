"""DTOs for FetchEventUseCase: what asks and what comes back."""

from pydantic import BaseModel, ConfigDict

from bugflow.shared.domain.values.caller import Caller


class FetchEventRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ledger_id: str
    caller: Caller
    #: The event's place in the ledger, counting from 1.
    number: int


class FetchEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: The event's bytes, as the ledger's file holds them.
    data: bytes
