"""An adapter from the review context's worktree interface to the work
context's.

The parameters and the return value already have the same types on both
sides, so no data is translated. Only the error is: the work context's
``WorktreeUnavailableError`` becomes the review context's.
"""

from pathlib import Path

from bugflow.review.domain.errors import WorktreeUnavailableError
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.work.domain.errors import (
    WorktreeUnavailableError as WorkWorktreeUnavailableError,
)
from bugflow.work.domain.services.worktree import (
    WorktreeService as WorkWorktreeService,
)


class WorkWorktrees:
    """Implements the review context's ``WorktreeService`` with the work
    context's."""

    def __init__(self, worktrees: WorkWorktreeService) -> None:
        self._worktrees = worktrees

    def prepare(
        self,
        ref: PullRequestRef,
        head_sha: str,
        into: Path,
        base_sha: str = "",
    ) -> tuple[str, ...]:
        try:
            return self._worktrees.prepare(ref, head_sha, into, base_sha)
        except WorkWorktreeUnavailableError as exc:
            raise WorktreeUnavailableError(str(exc)) from exc
