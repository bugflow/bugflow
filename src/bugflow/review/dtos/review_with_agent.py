"""What the activities of a checkout agent's review take from the
workflow and return to it.

A workflow engine records these, so their fields are not renamed or
retyped. A new field is added with a default, so that a history
recorded before it still decodes.
"""

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.delegation import Handle
from bugflow.review.domain.models.review import ReviewNote, ReviewVerdict
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class DispatchedReview(BaseModel):
    model_config = ConfigDict(frozen=True)

    handle: Handle | None = None
    withheld: tuple[str, ...] = ()
    reason: str = ""
    reused: ReviewVerdict | None = None


class ReviewAgentActivityRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: PullRequestRef
    head_sha: str
    base_sha: str = ""
    agent_id: str
    corpus_version: str = ""
    correlation: Correlation


class ReviewCollectActivityRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    review: ReviewAgentActivityRequest
    handle: Handle


class ReviewAgentActivityResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: ReviewVerdict | None = None
    reason: str = ""
    cost: dict[str, float] = {}
    note: ReviewNote | None = None
    running: bool = False
