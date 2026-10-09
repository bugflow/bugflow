"""The request and response of ``ReceiveDeliveryUseCase``."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from bugflow.forge.domain.models.delivery import Delivery
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

Outcome = Literal["evaluate", "close", "dismiss", "duplicate", "ignored"]


class ReceiveDeliveryRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    delivery: Delivery


class ReceiveDeliveryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: Outcome
    reason: str
    ref: PullRequestRef | None
    # The workflow run the delivery was passed to, if it was passed to one.
    evaluation: Correlation | None = None
