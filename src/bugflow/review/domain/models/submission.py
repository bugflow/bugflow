"""A submission: the parts of a pull request that a policy reads.

The forge context holds the whole pull request. This context has a type
of its own with only what a check or a judgement reads.
"""

import hashlib
import json
from dataclasses import asdict, dataclass

from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


@dataclass(frozen=True, kw_only=True)
class SubmissionCommit:
    sha: str
    message: str
    #: The paths this commit changed, so that a judge can tell which
    #: change belongs to which commit.
    files: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class SubmissionFile:
    path: str
    additions: int
    deletions: int
    #: The file's diff. None if the forge gave none, as it does for a
    #: binary file or a very large diff.
    patch: str | None


@dataclass(frozen=True, kw_only=True)
class Submission:
    title: str
    body: str
    commits: tuple[SubmissionCommit, ...]
    files: tuple[SubmissionFile, ...]

    @property
    def content_id(self) -> str:
        """A SHA-256 hash of the submission's content."""
        canonical = json.dumps(asdict(self), separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, kw_only=True)
class SubmissionRef:
    """A reference to a stored submission.

    The steps of a workflow pass this and not the submission, so that
    what the workflow engine records stays small however large the pull
    request is.
    """

    #: The hash of the stored content.
    snapshot_id: str
    ref: PullRequestRef
