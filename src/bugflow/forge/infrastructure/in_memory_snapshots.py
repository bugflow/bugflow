"""A snapshot store that keeps snapshots in memory, for tests."""

import json
from dataclasses import replace

from bugflow.forge.domain.errors import SnapshotNotFoundError
from bugflow.forge.domain.models.pull_request import (
    PullRequestSnapshot,
    SnapshotRef,
)
from bugflow.shared.domain.errors import ContentTooLargeError
from bugflow.shared.domain.repositories.repository_associations import (
    RepositoryAssociations,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.domain.values.repository_association import (
    RepositoryAssociationUnresolvedError,
)
from bugflow.shared.infrastructure.serde import to_json


class InMemorySnapshotStore:
    def __init__(
        self, associations: RepositoryAssociations | None = None
    ) -> None:
        self.snapshots: dict[str, PullRequestSnapshot] = {}
        self._associations = associations

    def has_contribution(
        self,
        ref: PullRequestRef,
        emails: frozenset[str],
        *,
        origin: str | None = None,
    ) -> bool:
        aliases = {email for email in emails if email.strip()}
        return any(
            (
                snapshot.ref == ref
                if origin is None
                else (
                    snapshot.ref.forge == ref.forge
                    and snapshot.ref.number == ref.number
                    and self._origin(snapshot.content_id) == origin
                )
            )
            and any(
                commit.author.email in aliases
                or commit.committer.email in aliases
                for commit in snapshot.commits
            )
            for snapshot in self.snapshots.values()
        )

    def put(self, snapshot: PullRequestSnapshot) -> SnapshotRef:
        reference = SnapshotRef(
            snapshot_id=snapshot.content_id, ref=snapshot.ref
        )
        self.snapshots.setdefault(reference.snapshot_id, snapshot)
        return reference

    def get(self, reference: SnapshotRef) -> PullRequestSnapshot:
        if reference.origin is not None:
            raise ValueError("canonical snapshots require the bounded reader")
        try:
            return self.snapshots[reference.snapshot_id]
        except KeyError as exc:
            raise SnapshotNotFoundError(
                f"no stored snapshot {reference.snapshot_id}"
            ) from exc

    def get_bounded(
        self, reference: SnapshotRef, max_bytes: int
    ) -> tuple[PullRequestSnapshot, int]:
        snapshot = self.get(replace(reference, origin=None))
        if reference.origin is not None:
            origin = self._origin(reference.snapshot_id)
            if origin is None:
                raise RepositoryAssociationUnresolvedError(
                    "snapshot has no repository association"
                )
            if (
                origin != reference.origin
                or snapshot.ref.forge != reference.ref.forge
                or snapshot.ref.number != reference.ref.number
            ):
                raise SnapshotNotFoundError("no stored snapshot in this scope")
        size = 1024 + len(
            json.dumps(to_json(snapshot), ensure_ascii=False).encode("utf-8")
        )
        if size > max_bytes:
            raise ContentTooLargeError("snapshot exceeds the byte allowance")
        return snapshot, size

    def _origin(self, snapshot_id: str) -> str | None:
        origin = (
            self._associations.origin_for("snapshot", snapshot_id)
            if self._associations is not None
            else None
        )
        return str(origin) if origin is not None else None
