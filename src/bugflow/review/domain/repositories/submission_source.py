"""The interface for reading a stored submission."""

from typing import Protocol

from bugflow.review.domain.models.submission import Submission, SubmissionRef
from bugflow.shared.domain.repositories.base import BaseRepository


class SubmissionSourceRepository(BaseRepository[Submission], Protocol):
    def get(self, reference: SubmissionRef) -> Submission:
        """Return the submission. Raises ``SubmissionNotFoundError`` if
        there is none under the reference."""
        ...


class BoundedSubmissionSourceRepository(Protocol):
    def get_bounded(
        self, reference: SubmissionRef, max_bytes: int
    ) -> tuple[Submission, int]:
        """Return a submission and the byte charge for its stored source."""
        ...
