"""Tests of the grader a server has when none is set up."""

from bugflow.review.domain.models.grading import Grading, Writeup
from bugflow.review.domain.services.grader import GraderService
from bugflow.review.infrastructure.ungraded_write_ups import (
    NO_GRADER,
    UngradedWriteUps,
)

WRITE_UP = Writeup(
    agent_id="security",
    head_sha="abc1234",
    write_up="It holds.\n\n## For the author\n\nNothing to change.",
    outcome="completed",
)


def test_a_write_up_is_given_no_verdict() -> None:
    grader: GraderService = UngradedWriteUps()
    assert grader.grade(WRITE_UP) == Grading(
        status=None,
        detail="no grader is configured; the write-up is kept and not graded",
        note_fit=False,
    )


def test_the_note_is_not_shown_and_no_model_was_asked() -> None:
    grading = UngradedWriteUps().grade(WRITE_UP)
    assert grading.note_fit is False
    assert grading.calls == ()
    assert grading.detail == NO_GRADER


def test_a_run_that_did_not_answer_is_treated_the_same() -> None:
    failed = Writeup(
        agent_id="security", head_sha="abc1234", write_up="", outcome="failed"
    )
    assert UngradedWriteUps().grade(failed).status is None
