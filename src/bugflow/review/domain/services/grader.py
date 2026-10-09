"""The interface to the grader."""

from typing import Protocol

from bugflow.review.domain.models.grading import Grading, Writeup


class GraderService(Protocol):
    def grade(self, writeup: Writeup) -> Grading:
        """Return the verdict the write-up supports. The grading's
        status is None if the write-up supports none.

        Raises ``GraderUnavailableError`` if the grader could not be
        asked. The error carries any calls that were made.
        """
        ...
