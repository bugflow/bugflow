"""The request and response of ``WaitReviewUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.delegation import Handle
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class WaitReviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: PullRequestRef
    head_sha: str
    agent_id: str
    correlation: Correlation
    handle: Handle
    # How long to wait, in seconds. Zero means the time the handle
    # gives, which the runner's adapter chose.
    patience: float = 0.0


class WaitReviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    # True if the run has something new to read. False means the time
    # ran out, not that the run failed.
    ready: bool
