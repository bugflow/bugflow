"""The request and response of the activity that answers one policy.

The caller names a policy and does not know whether a judge or a check
answers it. The response is the same either way.
"""

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.corpus import Corpus
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.submission import SubmissionRef
from bugflow.shared.domain.values.correlation import Correlation


class AssessPolicyRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_id: str | None
    snapshot: SubmissionRef
    corpus: Corpus
    correlation: Correlation
    use_judge: bool = True
    head_sha: str | None = None


class AssessPolicyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    findings: tuple[Finding, ...]
    status: str
    unavailable: tuple[str, ...] = ()
    answered: tuple[str, ...] = ()
