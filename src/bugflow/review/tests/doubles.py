"""Stand-ins that several of the review tests use."""

from datetime import UTC, datetime

from bugflow.review.domain.errors import SubmissionNotFoundError
from bugflow.review.domain.models.submission import Submission, SubmissionRef
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

NOW = datetime(2030, 3, 12, tzinfo=UTC)


class FixedClock:
    """A clock that always says ``NOW``."""

    def now(self) -> datetime:
        return NOW


class InMemorySubmissions:
    """Stored submissions, kept in a dictionary under the hash of their
    content. ``read`` counts how many times one was fetched."""

    def __init__(self) -> None:
        self.stored: dict[str, Submission] = {}
        self.read = 0

    def put(
        self, ref: PullRequestRef, submission: Submission
    ) -> SubmissionRef:
        self.stored[submission.content_id] = submission
        return SubmissionRef(snapshot_id=submission.content_id, ref=ref)

    def get(self, reference: SubmissionRef) -> Submission:
        self.read += 1
        try:
            return self.stored[reference.snapshot_id]
        except KeyError as exc:
            raise SubmissionNotFoundError(reference.snapshot_id) from exc
