"""A forge that answers from files on disk, for tests and for replaying a
recorded pull request.

The files are laid out as ``<root>/pulls/<number>/pull.json``,
``commits.json`` and ``files.json``. Each holds the response the real
adapter would get from the forge's API. A pull request recorded from
Forgejo also has ``pull.diff``, its whole diff.

Nothing is written to any forge. Comments, labels and statuses that would
have been written are kept in memory, where a test can look at them.
"""

import json
from pathlib import Path
from typing import Any

from bugflow.forge.domain.errors import ForgeRejectedError
from bugflow.forge.domain.models.pull_request import PullRequestSnapshot
from bugflow.forge.domain.services.forge import CommitState
from bugflow.forge.infrastructure import forgejo, github
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class RecordedForge:
    def __init__(self, root: Path) -> None:
        self._root = root
        # Comments added: pull request number -> comment id -> body.
        self.comments: dict[int, dict[int, str]] = {}
        self.labels: dict[int, set[str]] = {}
        # Statuses set: commit sha -> context -> (state, description).
        self.statuses: dict[str, dict[str, tuple[str, str]]] = {}
        self._next_comment_id = 1

    def is_open(self, ref: PullRequestRef) -> bool:
        """Always answers that the pull request is not open. A recording is of
        a moment that has passed, so nothing should wait for it to close.
        """
        return (self._root / "pulls" / str(ref.number)).is_dir()

    def fetch_snapshot(self, ref: PullRequestRef) -> PullRequestSnapshot:
        directory = self._root / "pulls" / str(ref.number)
        if not directory.is_dir():
            raise ForgeRejectedError(
                f"no recording of {ref} under {self._root}"
            )

        def load(name: str) -> Any:
            return json.loads((directory / name).read_text())

        if ref.forge == "forgejo":
            return forgejo.snapshot_from_payloads(
                ref,
                load("pull.json"),
                load("commits.json"),
                load("files.json"),
                (directory / "pull.diff").read_text(),
            )
        return github.snapshot_from_payloads(
            ref, load("pull.json"), load("commits.json"), load("files.json")
        )

    def add_comment(self, ref: PullRequestRef, marker: str, body: str) -> int:
        comments = self.comments.setdefault(ref.number, {})
        for comment_id, existing in comments.items():
            if marker in existing:
                return comment_id
        comment_id = self._next_comment_id
        self._next_comment_id += 1
        comments[comment_id] = body
        return comment_id

    def set_labels(
        self,
        ref: PullRequestRef,
        add: frozenset[str],
        remove: frozenset[str],
    ) -> None:
        labels = self.labels.setdefault(ref.number, set())
        labels.difference_update(remove)
        labels.update(add)

    def set_commit_status(
        self,
        ref: PullRequestRef,
        sha: str,
        context: str,
        state: CommitState,
        description: str,
    ) -> None:
        self.statuses.setdefault(sha, {})[context] = (state, description)
