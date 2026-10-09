"""The requests and responses of the four use cases in
``review_range``."""

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.delegation import Handle, Run
from bugflow.shared.domain.values.budget import Budget
from bugflow.shared.domain.values.correlation import Correlation


class DispatchRangeReviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    forge: str
    repo: str
    layer: str
    agent_id: str
    instructions: str
    # The two commits the review compares: where the last stocktake
    # got to, and the last one merged since. The base is None on a
    # layer's first stocktake.
    base_sha: str | None
    head_sha: str
    budget: Budget | None = None
    correlation: Correlation
    # A reason this run must not be started, decided before the use
    # case was called: for example nothing allows the money. The use
    # case records the reason and starts nothing.
    refusal: str = ""


class DispatchRangeReviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    handle: Handle | None = None
    reason: str = ""


class WaitRangeReviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    forge: str
    repo: str
    layer: str
    agent_id: str
    head_sha: str
    handle: Handle
    correlation: Correlation
    # How long to wait, in seconds. Zero means the time the handle
    # gives.
    patience: float = 0.0


class WaitRangeReviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    ready: bool


class CollectRangeReviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    forge: str
    repo: str
    layer: str
    agent_id: str
    head_sha: str
    handle: Handle
    correlation: Correlation


class CollectRangeReviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    run: Run | None = None
    reason: str = ""


class GradeRangeReviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    forge: str
    repo: str
    layer: str
    agent_id: str
    head_sha: str
    run: Run
    correlation: Correlation


class GradeRangeReviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    # The verdict the write-up supports. None if it supports none.
    status: str | None = None
    detail: str = ""
    # The note to the reader, if the grader found it fit to show.
    note: str = ""
    # The whole write-up, given only when there is no note.
    write_up: str = ""
