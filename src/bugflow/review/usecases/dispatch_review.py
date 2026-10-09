"""Start a checkout agent's review of a commit, without waiting for it.

A review by a checkout agent takes four steps, and each is a use case:
this one, then ``wait_review``, ``collect_review`` and ``grade_review``.
A run can take minutes, so the step that starts it returns at once with
a handle. Each step records what it did.
"""

from dataclasses import asdict
from typing import Any

from bugflow.review.domain.errors import (
    AgentUnavailableError,
    WorktreeUnavailableError,
)
from bugflow.review.domain.facts import AGENT_DISPATCHED, REVIEW_GRADED
from bugflow.review.domain.models.delegation import Task
from bugflow.review.domain.models.recorder import Recorder
from bugflow.review.domain.models.review import ReviewVerdict
from bugflow.review.domain.services.delegated_work import DelegatedWorkService
from bugflow.review.domain.services.journal import JournalService
from bugflow.review.domain.services.worktree import WorktreeService
from bugflow.review.dtos.dispatch_review import (
    DispatchReviewRequest,
    DispatchReviewResponse,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.services.clock import ClockService

#: The shape of the answer the agent must give: an object with one
#: text field, the write-up.
WRITE_UP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"write_up": {"type": "string"}},
    "required": ["write_up"],
}

#: How many answers the agent may give before one that does not match
#: the shape ends the run.
ATTEMPTS = 3


class DispatchReviewUseCase:
    def __init__(
        self,
        worktrees: WorktreeService | None,
        agent: DelegatedWorkService,
        journal: JournalService,
        clock: ClockService,
    ) -> None:
        """``worktrees`` prepares a directory for a runner that reads
        one. It is None for a runner that fetches the repository
        itself."""
        self._worktrees = worktrees
        self._agent = agent
        self._journal = journal
        self._clock = clock

    def execute(
        self, request: DispatchReviewRequest
    ) -> DispatchReviewResponse:
        """Start the run and return its handle, or the reason no run
        was started.

        No run is started in four cases, and each is recorded:

        - The request carries a refusal.
        - This reviewer, with its present settings, has already given a
          verdict on this commit. That verdict is returned. A run costs
          money, and the answer is already known.
        - The worktree could not be prepared.
        - The runner could not start the run.
        """
        if request.refusal:
            self._record(
                request,
                "refused",
                {"step": "refused", "reason": request.refusal},
            )
            return DispatchReviewResponse(reason=request.refusal)
        reused = self._reviewed(request)
        if reused is not None:
            reviewed_in, verdict = reused
            self._record(
                request,
                "reused",
                {
                    "step": "reused",
                    "fingerprint": self._agent.fingerprint,
                    "reviewed_in": reviewed_in,
                },
            )
            return DispatchReviewResponse(
                reason="reviewed already at this commit, by this version",
                reused=verdict,
            )
        removed: tuple[str, ...] = ()
        if self._worktrees is not None:
            try:
                removed = self._worktrees.prepare(
                    request.ref,
                    request.head_sha,
                    request.worktree,
                    request.base_sha,
                )
            except WorktreeUnavailableError as exc:
                self._record(
                    request,
                    "no-worktree",
                    {"step": "no-worktree", "reason": str(exc)},
                )
                return DispatchReviewResponse(
                    handle=None, reason=f"no worktree: {exc}"
                )

        task = Task(
            instructions=request.instructions,
            inputs=str(request.worktree) if self._worktrees else None,
            repository=f"{request.ref.owner}/{request.ref.repo}",
            commit=request.base_sha,
            head=request.head_sha,
            artifact_schema=WRITE_UP_SCHEMA,
            budget=request.budget,
            attempts=ATTEMPTS,
        )
        try:
            handle = self._agent.dispatch(task)
        except AgentUnavailableError as exc:
            self._record(
                request,
                "unavailable",
                {"step": "unavailable", "reason": str(exc)},
            )
            return DispatchReviewResponse(
                handle=None, reason=f"the agent did not run: {exc}"
            )
        self._record(
            request,
            "",
            {
                "step": "dispatched",
                "runner": handle.runner,
                "fingerprint": handle.fingerprint,
                "remote_id": handle.remote_id,
                # The limit, so that it can be read beside the cost
                # that collecting records.
                "budget": asdict(handle.budget) if handle.budget else None,
                # The files the agent was not shown.
                "withheld": list(removed),
            },
        )
        return DispatchReviewResponse(handle=handle, withheld=removed)

    def _record(
        self,
        request: DispatchReviewRequest,
        step: str,
        payload: dict[str, Any],
    ) -> None:
        """Write one "agent dispatched" entry.

        The payload's ``step`` says what happened: "dispatched" for a
        run that started, and "refused", "reused", "no-worktree" or
        "unavailable" for the four ways none did. They are recorded
        apart because each is put right in a different place.
        """
        self._journal.append(
            [
                self._entry(
                    request, step, {"agent_id": request.agent_id, **payload}
                )
            ]
        )

    def _entry(
        self,
        request: DispatchReviewRequest,
        step: str,
        payload: dict[str, Any],
    ) -> JournalEntry:
        recorder = Recorder(
            request.ref,
            request.correlation,
            request.corpus_version or None,
            self._clock.now(),
        )
        return recorder.entry(
            AGENT_DISPATCHED,
            f"{request.agent_id}/{step}" if step else request.agent_id,
            payload,
            commit_sha=request.head_sha,
            agent_id=request.agent_id,
        )

    def _reviewed(
        self, request: DispatchReviewRequest
    ) -> tuple[str, ReviewVerdict] | None:
        """Find the verdict this reviewer already gave on this commit.

        It looks for a workflow run in which a run of this reviewer was
        dispatched for this commit with the runner's present
        fingerprint, and was then graded with a verdict. Returns that
        workflow run's id and the verdict, taking the latest if there
        are several. Returns None if there is none.
        """
        dispatched_in = {
            e.run_id
            for e in self._journal.events_for_pull_request(
                request.ref, AGENT_DISPATCHED
            )
            if e.payload.get("step") == "dispatched"
            and e.payload.get("agent_id") == request.agent_id
            and e.payload.get("fingerprint") == self._agent.fingerprint
            and e.commit_sha == request.head_sha
        }
        graded = [
            e
            for e in self._journal.events_for_pull_request(
                request.ref, REVIEW_GRADED
            )
            if e.payload.get("agent_id") == request.agent_id
            and e.commit_sha == request.head_sha
            and e.run_id in dispatched_in
            and e.payload.get("status") is not None
        ]
        if not graded:
            return None
        latest = graded[-1]
        return latest.run_id, ReviewVerdict(
            agent_id=request.agent_id,
            head_sha=request.head_sha,
            status=latest.payload["status"],
        )
