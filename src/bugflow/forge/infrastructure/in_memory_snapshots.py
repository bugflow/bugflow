"""A snapshot store that keeps snapshots in memory, for tests."""

import json

from bugflow.forge.domain.errors import SnapshotNotFoundError
from bugflow.forge.domain.models.pull_request import (
    PullRequestSnapshot,
    SnapshotRef,
)
from bugflow.shared.domain.errors import ContentTooLargeError
from bugflow.shared.infrastructure.serde import to_json


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

    def get_bounded(
        self, reference: SnapshotRef, max_bytes: int
    ) -> tuple[PullRequestSnapshot, int]:
        snapshot = self.get(reference)
        size = 1024 + len(
            json.dumps(to_json(snapshot), ensure_ascii=False).encode("utf-8")
        )
        if size > max_bytes:
            raise ContentTooLargeError("snapshot exceeds the byte allowance")
        return snapshot, size
