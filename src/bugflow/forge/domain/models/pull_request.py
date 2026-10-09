"""The snapshot of a pull request: a copy of it as it was at one moment."""

import hashlib
import json
from dataclasses import asdict, dataclass

from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


@dataclass(frozen=True, kw_only=True)
class Authorship:
    """Who a commit says did something.

    Git records a name and an email for a commit's author, and again for
    its committer. Both are free text, chosen by whoever made the commit.

    ``login`` is different. It is not in the commit. The forge looks up
    the email among the addresses its users have verified, and attaches
    the matching account if there is one. It is empty if nothing matched,
    and it can change later: a user who adds an old address to their
    account becomes the author of every commit that used it.

    So treat the email as the fact and the login as the forge's current
    guess. Do not use the login as a key for anything that must stay
    true.
    """

    name: str = ""
    email: str = ""
    login: str = ""


@dataclass(frozen=True, kw_only=True)
class CommitSnapshot:
    """One commit of a pull request."""

    sha: str
    message: str
    #: Who wrote the change, and who committed it. They differ after a
    #: rebase, a cherry-pick, or when a maintainer applies someone's
    #: patch, so both are kept.
    author: Authorship = Authorship()
    committer: Authorship = Authorship()
    #: Whether the commit has a signature that the forge could verify.
    #: Without one, nothing confirms the author line.
    verified: bool = False
    #: When not verified, the forge's reason: for example unsigned, or
    #: signed with a key it does not know.
    verification_reason: str = ""
    #: The paths this commit changed, in the forge's order. Empty if the
    #: forge did not say.
    files: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        """The first line of the commit message."""
        return self.message.split("\n", 1)[0]


@dataclass(frozen=True, kw_only=True)
class ChangedFile:
    """One file a pull request changes."""

    path: str
    additions: int
    deletions: int
    #: The file's diff. None when the forge leaves it out, as GitHub
    #: does for binary files and very large diffs.
    patch: str | None


@dataclass(frozen=True, kw_only=True)
class PullRequestSummary:
    """The main facts about a pull request, without its content."""

    ref: PullRequestRef
    title: str
    head_branch: str
    base_branch: str
    commit_count: int
    file_count: int
    changed_lines: int
    #: The last commit of the pull request, or None if it has none.
    head_sha: str | None = None
    #: The commit the target branch was at when the snapshot was taken.
    #: A review compares against this commit and not against the branch,
    #: because the branch moves on as other changes are merged.
    base_sha: str = ""


@dataclass(frozen=True, kw_only=True)
class PullRequestSnapshot:
    """A pull request as it was when it was read from the forge."""

    ref: PullRequestRef
    title: str
    body: str
    head_branch: str
    base_branch: str
    #: The commit the target branch was at, as the forge reported it.
    base_sha: str = ""
    #: The account that opened the pull request.
    #:
    #: Names of people are kept in snapshots, which can be deleted. They
    #: are deliberately not written to the journal, which can never be
    #: changed: a name written there could not be removed if a person
    #: asked.
    author_login: str = ""
    commits: tuple[CommitSnapshot, ...]
    files: tuple[ChangedFile, ...]

    @property
    def changed_lines(self) -> int:
        """Lines added plus lines deleted, over all files."""
        return sum(f.additions + f.deletions for f in self.files)

    @property
    def content_id(self) -> str:
        """A SHA-256 hash of everything in the snapshot. Two snapshots of
        a pull request that has not changed have the same hash."""
        canonical = json.dumps(asdict(self), separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def summary(self) -> PullRequestSummary:
        return PullRequestSummary(
            ref=self.ref,
            title=self.title,
            head_branch=self.head_branch,
            base_branch=self.base_branch,
            commit_count=len(self.commits),
            file_count=len(self.files),
            changed_lines=self.changed_lines,
            head_sha=self.commits[-1].sha if self.commits else None,
            base_sha=self.base_sha,
        )


@dataclass(frozen=True, kw_only=True)
class SnapshotRef:
    """A reference to a stored snapshot: the hash of its content, and the
    pull request it is of.

    A workflow passes this between its steps in place of the snapshot.
    A workflow engine records everything passed between steps, and a
    reference is small however large the pull request is.
    """

    snapshot_id: str
    ref: PullRequestRef
