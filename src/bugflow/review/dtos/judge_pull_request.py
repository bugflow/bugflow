"""The request and response of ``JudgePullRequestUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.corpus import Corpus
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.submission import SubmissionRef
from bugflow.shared.domain.values.correlation import Correlation


class JudgePullRequestRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    # The stored submission to judge.
    snapshot: SubmissionRef
    corpus: Corpus
    correlation: Correlation
    # False to judge nothing and only record that judging was skipped.
    use_judge: bool = True
    # The one policy to judge. None to judge every policy the judge has.
    policy_id: str | None = None
    # False while the caller will try again. A judge that is unavailable
    # for now then raises, and nothing is recorded. True on the last
    # try, when the failure is recorded as the result.
    final_attempt: bool = True
    # The commit being judged, to be recorded. A submission is
    # identified by its content and does not say which commit it was
    # read at.
    head_sha: str | None = None


class JudgePullRequestResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    findings: tuple[Finding, ...]
    # Which model judged, or why nothing did. With several policies it
    # has one part for each.
    status: str
    # The policies the judge could not answer. They did not pass.
    unavailable: tuple[str, ...] = ()
    # The policies the judge did answer.
    answered: tuple[str, ...] = ()
