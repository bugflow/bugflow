"""A grader for a server with no grader set up: it grades nothing.

A write-up handed to it is kept by whoever handed it over. It is given
no verdict, so the pull request's label stays in progress for that
reviewer, and its note is not shown to the author.
"""

from bugflow.review.domain.models.grading import Grading, Writeup

#: The reason every grading from this grader gives.
NO_GRADER = "no grader is configured; the write-up is kept and not graded"


class UngradedWriteUps:
    """Implements ``GraderService`` without asking anything."""

    def grade(self, writeup: Writeup) -> Grading:
        return Grading(status=None, detail=NO_GRADER, note_fit=False)
