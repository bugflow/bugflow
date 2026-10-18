"""Bounded submissions preserve both the scope and the storage charge."""

import pytest

from bugflow.apps.shared.submission_source import ForgeBoundedSubmissionSource
from bugflow.forge.domain.models.pull_request import PullRequestSnapshot
from bugflow.forge.infrastructure.in_memory_snapshots import (
    InMemorySnapshotStore,
)
from bugflow.review.domain.errors import SubmissionNotFoundError
from bugflow.review.domain.models.submission import SubmissionRef
from bugflow.shared.domain.errors import ContentTooLargeError
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="owner", repo="repo", number=1)


def test_bounded_submission_keeps_the_source_charge_and_scope() -> None:
    snapshots = InMemorySnapshotStore()
    snapshot = PullRequestSnapshot(
        ref=REF,
        title="Title",
        body="Body",
        head_branch="change",
        base_branch="main",
        commits=(),
        files=(),
    )
    stored = snapshots.put(snapshot)
    source = ForgeBoundedSubmissionSource(snapshots)
    reference = SubmissionRef(snapshot_id=stored.snapshot_id, ref=REF)
    submission, size = source.get_bounded(reference, 100_000)
    assert submission.body == "Body"
    assert size == snapshots.get_bounded(stored, 100_000)[1]
    with pytest.raises(ContentTooLargeError):
        source.get_bounded(reference, size - 1)
    with pytest.raises(SubmissionNotFoundError):
        source.get_bounded(
            SubmissionRef(
                snapshot_id=stored.snapshot_id,
                ref=PullRequestRef(owner="other", repo="repo", number=1),
            ),
            100_000,
        )
    with pytest.raises(SubmissionNotFoundError):
        source.get_bounded(SubmissionRef(snapshot_id="gone", ref=REF), 100_000)
