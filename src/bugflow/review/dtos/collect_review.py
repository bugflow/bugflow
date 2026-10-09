"""The request and response of ``CollectReviewUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.delegation import Handle, Run
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class CollectReviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: PullRequestRef
    head_sha: str
    agent_id: str
    # The reviewer's own corpus version, which this step is recorded
    # under. Empty on a server with no reviewer installed.
    corpus_version: str = ""
    correlation: Correlation
    handle: Handle


class CollectReviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    # The run. None if the runner could not be asked for it at all.
    run: Run | None
    # Why there is nothing to grade. Empty if the run answered.
    reason: str = ""
