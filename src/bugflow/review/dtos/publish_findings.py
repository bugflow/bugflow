"""The request and response of ``PublishFindingsUseCase``."""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.review import ReviewNote, ReviewVerdict
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class PublishFindingsRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: PullRequestRef
    findings: tuple[Finding, ...]
    # How judging went, as the judging step reported it.
    judge_status: str
    # The policies the judge could not answer. They did not pass.
    unavailable: tuple[str, ...] = ()
    # The policies that answered, by a judge or a check. Only these can
    # withdraw a finding that an earlier evaluation raised.
    answered: tuple[str, ...] = ()
    # The text of each doctrine clause the findings cite, by clause id.
    clauses: Mapping[str, str] = Field(default_factory=dict)
    corpus_version: str
    correlation: Correlation
    # The pull request's last commit. The commit statuses are set on
    # it, and every verdict is about it.
    head_sha: str | None = None
    # The verdicts of checkout agents, which come from grading and not
    # from findings.
    verdicts: tuple[ReviewVerdict, ...] = ()
    # What each checkout agent says to the author.
    notes: tuple[ReviewNote, ...] = ()
    # The id of the stored submission this evaluation read.
    snapshot_id: str | None = None
    # False to write nothing to the forge, whatever the repository's
    # enforcement allows.
    publish: bool = True


class PublishFindingsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    # "published", or why nothing was.
    status: str
    label: str
    # The text of every reviewer's part, one after another. Empty if
    # no reviewer had anything to say.
    comment: str
    # The same text, by reviewer.
    comments: dict[str, str] = {}
    comment_id: int | None = None
    # The findings the previous evaluation raised and this one
    # withdrew.
    resolved: tuple[Finding, ...] = ()
    # The findings of policies dismissed on the pull request.
    dismissed: tuple[Finding, ...] = ()
    # The warnings kept out of the pull request on purpose.
    withheld: tuple[Finding, ...] = ()
    # The findings earlier evaluations raised that still stand,
    # although this evaluation did not raise them.
    carried: tuple[Finding, ...] = ()
