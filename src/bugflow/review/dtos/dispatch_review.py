"""The request and response of ``DispatchReviewUseCase``."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.delegation import Handle
from bugflow.review.domain.models.review import ReviewVerdict
from bugflow.shared.domain.values.budget import Budget
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class DispatchReviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: PullRequestRef
    # The commit to review.
    head_sha: str
    # The commit the pull request's base branch was at, so that the
    # reviewer can see what changed. Empty if not known.
    base_sha: str = ""
    agent_id: str
    # The reviewer's own corpus version, which this step is recorded
    # under. Empty on a server with no reviewer installed.
    corpus_version: str = ""
    # The reviewer's instructions. They are the only instructions the
    # run is given.
    instructions: str
    # The directory to prepare the worktree in. The caller owns it and
    # deletes it when the run is over.
    worktree: Path
    budget: Budget | None = None
    # A reason this run must not be started, decided before the use
    # case was called: for example nothing allows the money, or the
    # allowance for the period is used up. The use case records the
    # reason and starts nothing.
    refusal: str = ""
    correlation: Correlation


class DispatchReviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    # The handle to the run. None if no run was started.
    handle: Handle | None = None
    # The files the runner was not shown.
    withheld: tuple[str, ...] = ()
    # Why no run was started. Empty if one was.
    reason: str = ""
    # The verdict this reviewer already gave on this commit, if it has
    # one. No run is started then.
    reused: ReviewVerdict | None = None
