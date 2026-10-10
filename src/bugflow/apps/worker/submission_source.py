"""An adapter from the review context's submission source to the forge
context's snapshot store.

It turns a stored pull request snapshot into a submission. Who wrote a
commit is not carried across.
"""

from bugflow.forge.domain.models.pull_request import (
    SnapshotRef as ForgeSnapshotRef,
)
from bugflow.forge.domain.repositories.snapshots import SnapshotStoreRepository
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
        snapshot = self._snapshots.get(
            ForgeSnapshotRef(
                snapshot_id=reference.snapshot_id, ref=reference.ref
            )
        )
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
