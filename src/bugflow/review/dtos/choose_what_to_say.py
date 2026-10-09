"""The request and response of ``ChooseWhatToSayUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.finding import Finding
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class ChooseWhatToSayRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: PullRequestRef
    # The pull request's last commit, which the comment will be about.
    head_sha: str


class ChooseWhatToSayResponse(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    # The findings a comment should carry, the most severe first.
    findings: tuple[Finding, ...]
    # How many different findings were recorded about this commit,
    # whether or not they are in ``findings``.
    considered: int
