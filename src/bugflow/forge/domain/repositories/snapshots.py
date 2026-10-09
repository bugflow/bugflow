"""The interface for storing pull request snapshots."""

from typing import Protocol

from bugflow.forge.domain.models.pull_request import (
    PullRequestSnapshot,
    SnapshotRef,
)
from bugflow.shared.domain.repositories.base import BaseRepository


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
