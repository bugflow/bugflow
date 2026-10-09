"""The interface for preparing a worktree for a runner to read."""

from pathlib import Path
from typing import Protocol

from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class WorktreeService(Protocol):
    def prepare(
        self,
        ref: PullRequestRef,
        head_sha: str,
        into: Path,
        base_sha: str = "",
    ) -> tuple[str, ...]:
        """Put the files of commit ``head_sha`` under the directory
        ``into``, with the files a runner might read as instructions
        removed.

        If ``base_sha`` is given, that commit is fetched as well, so
        that the runner can see what changed. It is a commit and not a
        branch, because a branch moves on and would show changes that
        are not part of this pull request.

        Returns the paths that were removed, relative to ``into``, so
        that a record can say what the runner was not shown. The caller
        owns the directory and deletes it when the run is over.

        Raises ``WorktreeUnavailableError`` if the commit cannot be laid
        out.
        """
        ...
