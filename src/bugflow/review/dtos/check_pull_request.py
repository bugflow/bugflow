"""The request and response of ``CheckPullRequestUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.submission import SubmissionRef
from bugflow.shared.domain.values.correlation import Correlation


class CheckPullRequestRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    # The stored submission to check.
    snapshot: SubmissionRef
    # The id of the policy the check answers, and the id of the doctrine
    # clause its findings cite. Both are the reviewer's: this server has
    # no policy ids of its own.
    policy_id: str
    clause: str
    # The reviewer the policy belongs to, and that reviewer's corpus
    # version. On a server with no reviewer installed the agent id is
    # empty and the version is the evaluation's.
    corpus_version: str
    agent_id: str = ""
    correlation: Correlation


class CheckPullRequestResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    findings: tuple[Finding, ...]
    status: str
    # The policies that were answered: the one in the request.
    answered: tuple[str, ...] = ()
