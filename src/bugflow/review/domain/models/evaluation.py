"""What the steps of an evaluation pass to each other.

An evaluation is a sequence of steps, and each step is a use case. These
types are what the evaluation gives a step and what it gets back.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from bugflow.review.domain.models.corpus import Corpus
from bugflow.review.domain.models.delegation import Handle
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.review import ReviewNote, ReviewVerdict
from bugflow.review.domain.models.submission import SubmissionRef
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


@dataclass(frozen=True, kw_only=True)
class Observation:
    """A pull request as it was read at the start of an evaluation."""

    #: Where the submission is stored.
    submission: SubmissionRef
    title: str
    head_branch: str
    base_branch: str
    commit_count: int
    file_count: int
    changed_lines: int
    head_sha: str | None
    base_sha: str
    #: The corpus the evaluation runs under.
    corpus: Corpus
    #: True if this commit has already been judged under this corpus.
    judged_before: bool = False


@dataclass(frozen=True, kw_only=True)
class Answerable:
    """A policy this evaluation will ask about, and which class of model
    answers it.

    The class matters to the caller because calls to each class of model
    are queued and rate limited separately. An empty class means the
    policy is answered without a model.
    """

    policy_id: str
    model_class: str = ""


@dataclass(frozen=True, kw_only=True)
class Assessed:
    """What checking or judging found."""

    findings: tuple[Finding, ...]
    status: str
    #: The policies the judge could not answer.
    unavailable: tuple[str, ...] = ()
    #: The policies that were answered, by a judge or by a check. Only
    #: an answered policy can withdraw a finding that an earlier
    #: evaluation raised.
    answered: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ReviewAsked:
    """A request for one reviewer to review one commit."""

    ref: PullRequestRef
    head_sha: str
    base_sha: str
    agent_id: str
    #: That reviewer's own corpus version. Its run and its grading are
    #: recorded under it.
    corpus_version: str = ""
    correlation: Correlation


@dataclass(frozen=True, kw_only=True)
class Dispatched:
    """The result of dispatching a reviewer's task: a handle to the run,
    or the reason there is none."""

    handle: Handle | None = None
    reason: str = ""
    #: The verdict this reviewer already gave on this commit, used in
    #: place of a new run.
    reused: ReviewVerdict | None = None


@dataclass(frozen=True, kw_only=True)
class Reviewed:
    """One reviewer's review: a verdict, or the reason there is none."""

    verdict: ReviewVerdict | None = None
    note: ReviewNote | None = None
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class Publication:
    """Everything an evaluation found, as it is given to publishing."""

    ref: PullRequestRef
    findings: tuple[Finding, ...]
    judge_status: str
    #: The policies the judge could not answer.
    unavailable: tuple[str, ...]
    #: The policies that were answered, by a judge or by a check.
    answered: tuple[str, ...] = ()
    #: The text of each doctrine clause the findings cite, by clause id.
    clauses: Mapping[str, str] = field(default_factory=dict)
    corpus_version: str
    correlation: Correlation
    head_sha: str | None
    snapshot_id: str
    verdicts: tuple[ReviewVerdict, ...]
    notes: tuple[ReviewNote, ...]
    #: False for an evaluation that must write nothing to the pull
    #: request.
    publish: bool


@dataclass(frozen=True, kw_only=True)
class Published:
    """What publishing did."""

    status: str
    #: The findings the previous evaluation raised and this one did not.
    resolved: tuple[Finding, ...] = ()
