"""The request and response of ``ReadReviewRecordUseCase``."""

from pydantic import BaseModel, ConfigDict, Field

from bugflow.review.domain.models.history import (
    ContentReference,
    HistoryScope,
    ObservedReviewRun,
    StoredReviewEvent,
)
from bugflow.review.domain.models.record import ReviewRecord
from bugflow.review.domain.models.submission import Submission
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class ReadReviewRecordRequest(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    ref: PullRequestRef

    # The workflow run of the evaluation to read.
    correlation: Correlation


class ReadReviewRecordResponse(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    record: ReviewRecord
    # The ids of exchanges that a judgement names and the store no
    # longer has.
    missing_exchanges: tuple[str, ...] = ()
    events: tuple[StoredReviewEvent, ...] = ()
    submissions: dict[str, Submission] = Field(default_factory=dict)
    missing_submissions: tuple[str, ...] = ()
    content_references: tuple[ContentReference, ...] = ()


class ReadReviewHistoryRequest(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    scope: HistoryScope
    policy_id: str | None = None


class ReadReviewHistoryResponse(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    scope: HistoryScope
    policy_id: str | None
    runs: tuple[ObservedReviewRun, ...]
    observed_pr_numbers: tuple[int, ...]
    unobserved_pr_numbers: tuple[int, ...]
    event_count: int
