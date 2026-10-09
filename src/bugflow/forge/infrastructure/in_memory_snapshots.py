"""A snapshot store that keeps snapshots in memory, for tests."""

from bugflow.forge.domain.errors import SnapshotNotFoundError
from bugflow.forge.domain.models.pull_request import (
    PullRequestSnapshot,
    SnapshotRef,
)


class InMemorySnapshotStore:
    def __init__(self) -> None:
        self.snapshots: dict[str, PullRequestSnapshot] = {}

    def put(self, snapshot: PullRequestSnapshot) -> SnapshotRef:
        reference = SnapshotRef(
            snapshot_id=snapshot.content_id, ref=snapshot.ref
        )
        self.snapshots.setdefault(reference.snapshot_id, snapshot)
        return reference

    def get(self, reference: SnapshotRef) -> PullRequestSnapshot:
        try:
            return self.snapshots[reference.snapshot_id]
        except KeyError as exc:
            raise SnapshotNotFoundError(
                f"no stored snapshot {reference.snapshot_id}"
            ) from exc
