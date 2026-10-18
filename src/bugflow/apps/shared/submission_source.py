"""An adapter from the review context's submission source to the forge
context's snapshot store.

It turns a stored pull request snapshot into a submission. Who wrote a
commit is not carried across.
"""

from bugflow.forge.domain.errors import SnapshotNotFoundError
from bugflow.forge.domain.models.pull_request import (
    PullRequestSnapshot,
)
from bugflow.forge.domain.models.pull_request import (
    SnapshotRef as ForgeSnapshotRef,
)
from bugflow.forge.domain.repositories.snapshots import (
    BoundedSnapshotReader,
    SnapshotStoreRepository,
)
from bugflow.review.domain.errors import SubmissionNotFoundError
from bugflow.review.domain.models.submission import (
    Submission,
    SubmissionCommit,
    SubmissionFile,
    SubmissionRef,
)


class ForgeSubmissionSource:
    """Implements the review context's ``SubmissionSourceRepository`` by
    reading stored snapshots."""

    def __init__(self, snapshots: SnapshotStoreRepository) -> None:
        self._snapshots = snapshots

    def get(self, reference: SubmissionRef) -> Submission:
        if reference.origin is not None:
            raise ValueError(
                "canonical submissions require the bounded reader"
            )
        try:
            snapshot = self._snapshots.get(
                ForgeSnapshotRef(
                    snapshot_id=reference.snapshot_id, ref=reference.ref
                )
            )
        except SnapshotNotFoundError as exc:
            raise SubmissionNotFoundError("no stored submission") from exc
        return _submission(snapshot, reference)


class ForgeBoundedSubmissionSource:
    def __init__(self, snapshots: BoundedSnapshotReader) -> None:
        self._snapshots = snapshots

    def get_bounded(
        self, reference: SubmissionRef, max_bytes: int
    ) -> tuple[Submission, int]:
        try:
            snapshot, size = self._snapshots.get_bounded(
                ForgeSnapshotRef(
                    snapshot_id=reference.snapshot_id,
                    ref=reference.ref,
                    origin=reference.origin,
                ),
                max_bytes,
            )
        except SnapshotNotFoundError as exc:
            raise SubmissionNotFoundError("no stored submission") from exc
        return _submission(snapshot, reference), size


def _submission(
    snapshot: PullRequestSnapshot, reference: SubmissionRef
) -> Submission:
    matches = (
        snapshot.ref == reference.ref
        if reference.origin is None
        else (
            snapshot.ref.forge == reference.ref.forge
            and snapshot.ref.number == reference.ref.number
        )
    )
    if not matches:
        raise SubmissionNotFoundError("no submission in this scope")
    return Submission(
        title=snapshot.title,
        body=snapshot.body,
        commits=tuple(
            SubmissionCommit(sha=c.sha, message=c.message, files=c.files)
            for c in snapshot.commits
        ),
        files=tuple(
            SubmissionFile(
                path=f.path,
                additions=f.additions,
                deletions=f.deletions,
                patch=f.patch,
            )
            for f in snapshot.files
        ),
    )
