"""The interface for storing pull request snapshots."""

from typing import Protocol

from bugflow.forge.domain.models.pull_request import (
    PullRequestSnapshot,
    SnapshotRef,
)
from bugflow.shared.domain.repositories.base import BaseRepository
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class ContributionReader(Protocol):
    def has_contribution(
        self, ref: PullRequestRef, emails: frozenset[str]
    ) -> bool:
        """Whether a retained snapshot names an email as author or committer.

        Match the exact pull request and email. Empty aliases grant nothing.
        """
        ...


class SnapshotStoreRepository(BaseRepository[PullRequestSnapshot], Protocol):
    def put(self, snapshot: PullRequestSnapshot) -> SnapshotRef:
        """Store a snapshot and return a reference to it. Storing a
        snapshot with the same content again stores nothing new and
        returns the same reference."""
        ...

    def get(self, reference: SnapshotRef) -> PullRequestSnapshot:
        """Return the snapshot. Raises ``SnapshotNotFoundError`` if there
        is none under the reference."""
        ...


class BoundedSnapshotReader(Protocol):
    def get_bounded(
        self, reference: SnapshotRef, max_bytes: int
    ) -> tuple[PullRequestSnapshot, int]:
        """Return content and its byte charge, or raise ContentTooLargeError.

        Refuse oversized content before transferring it from storage.
        """
        ...
