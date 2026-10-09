"""The request and response of ``GradeReviewUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.delegation import Run
from bugflow.review.domain.models.grading import Grading
from bugflow.review.domain.models.review import ReviewNote, ReviewVerdict
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class GradeReviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: PullRequestRef
    head_sha: str
    agent_id: str
    # The reviewer's own corpus version, which this step is recorded
    # under. Empty on a server with no reviewer installed.
    corpus_version: str = ""
    correlation: Correlation
    # The run whose write-up is graded.
    run: Run


class GradeReviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    grading: Grading
    # The verdict the write-up supports. None if it supports none.
    verdict: ReviewVerdict | None
    # Why there is no verdict. Empty if there is one.
    reason: str = ""
    # What the reviewer says to the author. None if there is no
    # verdict.
    note: ReviewNote | None = None
