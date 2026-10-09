"""The interface for preparing a worktree for a checkout agent to
read."""

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
        ``into``, and fetch ``base_sha`` too if it is given.

        Returns the paths that were removed because an agent might read
        them as instructions, relative to ``into``. The caller owns the
        directory and deletes it when the run is over.

        Raises ``WorktreeUnavailableError`` if the commit cannot be laid
        out.
        """
        ...
