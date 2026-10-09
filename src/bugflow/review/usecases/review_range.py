"""The four steps of a stocktake's review of its range: dispatch, wait,
collect and grade.

A pull request's review has the same four steps, in ``dispatch_review``,
``wait_review``, ``collect_review`` and ``grade_review``. Those are all
about one pull request and one commit. A stocktake's range has two
commits and no pull request, and a stocktake records facts of its own.
So the four steps are written again here for a range, over the same
interfaces.
"""

from datetime import datetime

from bugflow.review.domain.errors import (
    AgentUnavailableError,
    GraderUnavailableError,
)
from bugflow.review.domain.facts import (
    STOCKTAKE_DISPATCHED,
    STOCKTAKE_FOUND,
    STOCKTAKE_GRADED,
    STOCKTAKE_REVIEWED,
)
from bugflow.review.domain.models.delegation import Run, Task
from bugflow.review.domain.models.grading import (
    ANSWERED,
    Grading,
    Writeup,
    author_note,
)
from bugflow.review.domain.services.delegated_work import DelegatedWorkService
from bugflow.review.domain.services.grader import GraderService
from bugflow.review.domain.services.journal import JournalService
from bugflow.review.dtos.review_range import (
    CollectRangeReviewRequest,
    CollectRangeReviewResponse,
    DispatchRangeReviewRequest,
    DispatchRangeReviewResponse,
    GradeRangeReviewRequest,
    GradeRangeReviewResponse,
    WaitRangeReviewRequest,
    WaitRangeReviewResponse,
)
from bugflow.review.usecases.model_calls import called
from bugflow.shared.domain.models.call_record import CallRecord
from bugflow.shared.domain.models.journal_entry import JournalEntry, event_id
from bugflow.shared.domain.services.clock import ClockService

#: The shape of the answer a stocktake's review must give: the write-up,
#: and a list of findings. Each finding says where it is, the lines
#: that show it, and what is wrong. Findings come as data so that each
#: can be recorded as a fact of its own.
RANGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "write_up": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "where": {"type": "string"},
                    "quote": {"type": "string"},
                    "claim": {"type": "string"},
                    "kind": {"type": "string"},
                },
                "required": ["where", "quote", "claim"],
            },
        },
    },
    "required": ["write_up", "findings"],
}

#: How many answers the review may give before one that does not match
#: the shape ends the run.
RANGE_ATTEMPTS = 3


class DispatchRangeReviewUseCase:
    """Starts the review of a range and returns a handle to its run, or
    the reason no run was started.
    """

    def __init__(
        self,
        agent: DelegatedWorkService,
        journal: JournalService,
        clock: ClockService,
    ) -> None:
        self._agent = agent
        self._journal = journal
        self._clock = clock

    def execute(
        self, request: DispatchRangeReviewRequest
    ) -> DispatchRangeReviewResponse:
        """No run is started if the request carries a refusal, or if the
        runner cannot start one. Each case is recorded with its reason,
        so that a review that was not allowed can be told from one whose
        runner failed.
        """
        if request.refusal:
            self._journal.append(
                [self._refused(request, request.refusal, self._clock.now())]
            )
            return DispatchRangeReviewResponse(
                handle=None, reason=request.refusal
            )
        task = Task(
            instructions=request.instructions,
            inputs=None,
            repository=request.repo,
            # The review compares the commit the last stocktake got
            # to with the last one merged since. A layer's first
            # stocktake has no base, and reads the files as they are.
            commit=request.base_sha or request.head_sha,
            head=request.head_sha,
            artifact_schema=RANGE_SCHEMA,
            budget=request.budget,
            attempts=RANGE_ATTEMPTS,
        )
        try:
            handle = self._agent.dispatch(task)
        except AgentUnavailableError as exc:
            self._journal.append(
                [self._unavailable(request, str(exc), self._clock.now())]
            )
            return DispatchRangeReviewResponse(
                handle=None, reason=f"the agent did not run: {exc}"
            )
        self._journal.append(
            [
                self._dispatched(
                    request, handle.runner, handle.remote_id, self._clock.now()
                )
            ]
        )
        return DispatchRangeReviewResponse(handle=handle)

    def _entry(
        self,
        request: DispatchRangeReviewRequest,
        key: str,
        payload: dict[str, object],
        occurred_at: datetime,
    ) -> JournalEntry:
        """Build one "stocktake dispatched" entry."""
        return JournalEntry(
            event_id=event_id(request.correlation, STOCKTAKE_DISPATCHED, key),
            occurred_at=occurred_at,
            event_type=STOCKTAKE_DISPATCHED,
            forge=request.forge,
            repo=request.repo,
            pr_number=None,
            commit_sha=request.head_sha,
            corpus_version=None,
            workflow_id=request.correlation.workflow_id,
            run_id=request.correlation.run_id,
            agent_id=request.agent_id,
            payload={
                "layer": request.layer,
                "agent_id": request.agent_id,
                "base_sha": request.base_sha,
                "head_sha": request.head_sha,
                **payload,
            },
        )

    def _dispatched(
        self,
        request: DispatchRangeReviewRequest,
        runner: str,
        remote_id: str,
        occurred_at: datetime,
    ) -> JournalEntry:
        """The entry for a run that started. It gives the runner and the
        runner's name for the work, which is how a completion for the
        run is matched to this stocktake.
        """
        return self._entry(
            request,
            f"{request.agent_id}/dispatched",
            {
                "step": "dispatched",
                "runner": runner,
                "remote_id": remote_id,
            },
            occurred_at,
        )

    def _refused(
        self,
        request: DispatchRangeReviewRequest,
        reason: str,
        occurred_at: datetime,
    ) -> JournalEntry:
        """The entry for a review that was not allowed."""
        return self._entry(
            request,
            f"{request.agent_id}/refused",
            {"step": "refused", "reason": reason},
            occurred_at,
        )

    def _unavailable(
        self,
        request: DispatchRangeReviewRequest,
        reason: str,
        occurred_at: datetime,
    ) -> JournalEntry:
        """The entry for a review whose runner could not start it."""
        return self._entry(
            request,
            f"{request.agent_id}/unavailable",
            {"step": "unavailable", "reason": reason},
            occurred_at,
        )


class WaitRangeReviewUseCase:
    """Waits for the review's run to have something to read. A runner
    that cannot be reached is answered as "not ready".
    """

    def __init__(self, agent: DelegatedWorkService) -> None:
        self._agent = agent

    def execute(
        self, request: WaitRangeReviewRequest
    ) -> WaitRangeReviewResponse:
        try:
            ready = self._agent.wait(
                request.handle, request.patience or request.handle.patience
            )
        except AgentUnavailableError:
            return WaitRangeReviewResponse(ready=False)
        return WaitRangeReviewResponse(ready=ready)


class CollectRangeReviewUseCase:
    """Reads what the run produced, and records its outcome, its cost,
    its write-up and its findings.
    """

    def __init__(
        self,
        agent: DelegatedWorkService,
        journal: JournalService,
        clock: ClockService,
    ) -> None:
        self._agent = agent
        self._journal = journal
        self._clock = clock

    def execute(
        self, request: CollectRangeReviewRequest
    ) -> CollectRangeReviewResponse:
        try:
            run = self._agent.collect(request.handle)
        except AgentUnavailableError as exc:
            return CollectRangeReviewResponse(
                run=None, reason=f"the run could not be read: {exc}"
            )
        if run.outcome == "running":
            # Nothing is recorded for a run that is not finished. The
            # entry's id is made from the workflow run and the agent,
            # so only the first entry written would count, and it must
            # say how the run ended.
            return CollectRangeReviewResponse(
                run=run, reason="the run has not finished"
            )
        now = self._clock.now()
        self._journal.append(
            [
                self._reviewed(request, run, now),
                *self._found(request, run, now),
            ]
        )
        if run.outcome not in ANSWERED:
            said = run.outcome.replace("_", " ")
            return CollectRangeReviewResponse(
                run=run, reason=f"the run {said}: {run.detail}"
            )
        return CollectRangeReviewResponse(run=run)

    def _reviewed(
        self,
        request: CollectRangeReviewRequest,
        run: Run,
        occurred_at: datetime,
    ) -> JournalEntry:
        """The "stocktake reviewed" entry: the run's outcome, cost and
        write-up.
        """
        return JournalEntry(
            event_id=event_id(
                request.correlation, STOCKTAKE_REVIEWED, request.agent_id
            ),
            occurred_at=occurred_at,
            event_type=STOCKTAKE_REVIEWED,
            forge=request.forge,
            repo=request.repo,
            pr_number=None,
            commit_sha=request.head_sha,
            corpus_version=None,
            workflow_id=request.correlation.workflow_id,
            run_id=request.correlation.run_id,
            agent_id=request.agent_id,
            payload={
                "layer": request.layer,
                "agent_id": request.agent_id,
                "outcome": run.outcome,
                "cost": run.cost,
                "detail": run.detail,
                "write_up": str(run.artifact.get("write_up") or ""),
            },
        )

    def _found(
        self,
        request: CollectRangeReviewRequest,
        run: Run,
        occurred_at: datetime,
    ) -> list[JournalEntry]:
        """One "stocktake found" entry for each finding of a completed
        run.

        Only a completed run's findings are recorded. Its answer matched
        the shape, so each is a finding the reviewer stated. A finding's
        entry id is made from its position in the answer, so collecting
        the same run again records nothing new.
        """
        if run.outcome != "completed":
            return []
        findings = run.artifact.get("findings") or []
        return [
            JournalEntry(
                event_id=event_id(
                    request.correlation,
                    STOCKTAKE_FOUND,
                    f"{request.agent_id}/{index}",
                ),
                occurred_at=occurred_at,
                event_type=STOCKTAKE_FOUND,
                forge=request.forge,
                repo=request.repo,
                pr_number=None,
                commit_sha=request.head_sha,
                corpus_version=None,
                workflow_id=request.correlation.workflow_id,
                run_id=request.correlation.run_id,
                agent_id=request.agent_id,
                payload={
                    "layer": request.layer,
                    "agent_id": request.agent_id,
                    "index": index,
                    "where": str(finding.get("where") or ""),
                    "quote": str(finding.get("quote") or ""),
                    "claim": str(finding.get("claim") or ""),
                    "kind": str(finding.get("kind") or ""),
                },
            )
            for index, finding in enumerate(findings)
            if isinstance(finding, dict)
        ]


class GradeRangeReviewUseCase:
    """Has the review's write-up graded, records the grading, and
    returns the verdict with the text to show a reader.
    """

    def __init__(
        self,
        grader: GraderService,
        journal: JournalService,
        clock: ClockService,
    ) -> None:
        self._grader = grader
        self._journal = journal
        self._clock = clock

    def execute(
        self, request: GradeRangeReviewRequest
    ) -> GradeRangeReviewResponse:
        """Raises ``GraderUnavailableError`` if the grader cannot be asked.
        The calls it made are recorded first.
        """
        write_up = str(request.run.artifact.get("write_up") or "")
        try:
            grading = self._grader.grade(
                Writeup(
                    agent_id=request.agent_id,
                    head_sha=request.head_sha,
                    write_up=write_up,
                    outcome=request.run.outcome,
                    cost=request.run.cost,
                )
            )
        except GraderUnavailableError as exc:
            self._journal.append(
                self._called(request, exc.calls, self._clock.now())
            )
            raise
        now = self._clock.now()
        self._journal.append(
            [
                *self._called(request, grading.calls, now),
                self._graded(request, grading, now),
            ]
        )
        # The note to the reader if the grader found it fit to show,
        # and the whole write-up otherwise.
        note = author_note(write_up) if grading.note_fit else ""
        return GradeRangeReviewResponse(
            status=grading.status,
            detail=grading.detail,
            note=note,
            write_up="" if note else write_up.strip(),
        )

    def _called(
        self,
        request: GradeRangeReviewRequest,
        calls: tuple[CallRecord, ...],
        occurred_at: datetime,
    ) -> list[JournalEntry]:
        """The entries for the grader's calls to a model."""
        return called(
            calls,
            request.correlation,
            occurred_at,
            forge=request.forge,
            repo=request.repo,
            pr_number=None,
            commit_sha=request.head_sha,
            corpus_version=None,
            agent_id=request.agent_id,
        )

    def _graded(
        self,
        request: GradeRangeReviewRequest,
        grading: Grading,
        occurred_at: datetime,
    ) -> JournalEntry:
        """The "stocktake graded" entry. Its status is None if the
        write-up supports no verdict.
        """
        return JournalEntry(
            event_id=event_id(
                request.correlation, STOCKTAKE_GRADED, request.agent_id
            ),
            occurred_at=occurred_at,
            event_type=STOCKTAKE_GRADED,
            forge=request.forge,
            repo=request.repo,
            pr_number=None,
            commit_sha=request.head_sha,
            corpus_version=None,
            workflow_id=request.correlation.workflow_id,
            run_id=request.correlation.run_id,
            agent_id=request.agent_id,
            payload={
                "layer": request.layer,
                "agent_id": request.agent_id,
                "status": grading.status,
                "detail": grading.detail,
            },
        )
