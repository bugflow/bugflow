"""Have a checkout agent's write-up graded, and record the verdict.

The last of a review's four steps. It is a step of its own because
grading takes seconds: if it fails and is tried again, the run, which
took minutes and money, is not repeated.

The result is one verdict for one reviewer and one commit, or none. A
write-up that does not answer what was asked supports no verdict.
"""

from dataclasses import replace
from datetime import datetime

from bugflow.review.domain.errors import GraderUnavailableError
from bugflow.review.domain.facts import REVIEW_GRADED
from bugflow.review.domain.models.grading import Grading, Writeup, author_note
from bugflow.review.domain.models.recorder import Recorder
from bugflow.review.domain.models.review import ReviewNote, ReviewVerdict
from bugflow.review.domain.services.grader import GraderService
from bugflow.review.dtos.grade_review import (
    GradeReviewRequest,
    GradeReviewResponse,
)
from bugflow.review.usecases.model_calls import called
from bugflow.shared.domain.models.call_record import CallRecord
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService


def note_for(
    agent_id: str, head_sha: str, write_up: str, grading: Grading
) -> ReviewNote:
    """What the author is shown of a graded review.

    If the grader found the write-up's note to the author fit to show,
    that note. Otherwise the whole write-up, which the comment shows
    folded away.
    """
    note = author_note(write_up) if grading.note_fit else ""
    return ReviewNote(
        agent_id=agent_id,
        head_sha=head_sha,
        note=note,
        write_up="" if note else write_up.strip(),
    )


class GradeReviewUseCase:
    def __init__(
        self,
        grader: GraderService,
        journal: RecordingService,
        clock: ClockService,
    ) -> None:
        self._grader = grader
        self._journal = journal
        self._clock = clock

    def execute(self, request: GradeReviewRequest) -> GradeReviewResponse:
        """Grade the write-up and record the grading.

        Raises ``GraderUnavailableError`` if the grader cannot be
        asked. The calls it made are recorded first, because they were
        still paid for.
        """
        run = request.run
        write_up = str(run.artifact.get("write_up") or "")
        writeup = Writeup(
            agent_id=request.agent_id,
            head_sha=request.head_sha,
            write_up=write_up,
            outcome=run.outcome,
            cost=run.cost,
        )
        try:
            grading = self._grader.grade(writeup)
        except GraderUnavailableError as exc:
            self._journal.append(
                self._called(request, exc.calls, self._clock.now())
            )
            raise
        now = self._clock.now()
        self._journal.append(
            [
                *self._called(request, grading.calls, now),
                Recorder(
                    request.ref,
                    request.correlation,
                    request.corpus_version or None,
                    now,
                ).entry(
                    REVIEW_GRADED,
                    request.agent_id,
                    {
                        "agent_id": request.agent_id,
                        # None if the write-up supports no verdict.
                        "status": grading.status,
                        "detail": grading.detail,
                    },
                    commit_sha=request.head_sha,
                    agent_id=request.agent_id,
                ),
            ]
        )
        # The calls are recorded. They are left out of the response so
        # that a workflow does not carry them.
        grading = replace(grading, calls=())
        if grading.status is None:
            return GradeReviewResponse(
                grading=grading,
                verdict=None,
                reason=grading.detail or "the write-up answered nothing",
            )
        return GradeReviewResponse(
            grading=grading,
            verdict=ReviewVerdict(
                agent_id=request.agent_id,
                head_sha=request.head_sha,
                status=grading.status,
            ),
            note=note_for(
                request.agent_id, request.head_sha, write_up, grading
            ),
        )

    def _called(
        self,
        request: GradeReviewRequest,
        calls: tuple[CallRecord, ...],
        occurred_at: datetime,
    ) -> list[JournalEntry]:
        return called(
            calls,
            request.correlation,
            occurred_at,
            forge=request.ref.forge,
            repo=f"{request.ref.owner}/{request.ref.repo}",
            pr_number=request.ref.number,
            commit_sha=request.head_sha,
            corpus_version=request.corpus_version or None,
            agent_id=request.agent_id,
        )
