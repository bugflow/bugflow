"""The request and response of ``ReceiveCompletionUseCase``."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from bugflow.work.domain.models.completion import Completion

#: What happened to a completion.
#:
#: - "signalled": the workflow run that dispatched the work was told.
#: - "not_waiting": that workflow run had already ended.
#: - "unknown": the journal records no dispatch of this work.
Outcome = Literal["signalled", "not_waiting", "unknown"]


class ReceiveCompletionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    completion: Completion


class ReceiveCompletionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: Outcome
    # Why, for an outcome other than "signalled". Empty otherwise.
    reason: str
