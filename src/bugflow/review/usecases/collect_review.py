"""Read what a checkout agent's run produced, and record what it cost.

The third of a review's four steps. A run that stopped short, declined
or failed has not reviewed the commit. It is returned with the reason,
and the review goes no further.

The write-up is stored, and the journal entry gives the key it is
stored under.
"""

from typing import Any

from bugflow.review.domain.errors import AgentUnavailableError
from bugflow.review.domain.facts import AGENT_DISPATCHED
from bugflow.review.domain.models.delegation import Run
from bugflow.review.domain.models.grading import ANSWERED
from bugflow.review.domain.models.recorder import Recorder
from bugflow.review.domain.models.write_up import WriteUp
from bugflow.review.domain.repositories.write_up_archive import (
    WriteUpArchiveRepository,
)
from bugflow.review.domain.services.delegated_work import DelegatedWorkService
from bugflow.review.dtos.collect_review import (
    CollectReviewRequest,
    CollectReviewResponse,
)
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService


class CollectReviewUseCase:
    def __init__(
        self,
        agent: DelegatedWorkService,
        journal: RecordingService,
        clock: ClockService,
        write_ups: WriteUpArchiveRepository | None = None,
    ) -> None:
        """``write_ups`` is where write-ups are stored, or None to store
        none."""
        self._agent = agent
        self._journal = journal
        self._clock = clock
        self._write_ups = write_ups

    def execute(self, request: CollectReviewRequest) -> CollectReviewResponse:
        try:
            run = self._agent.collect(request.handle)
        except AgentUnavailableError as exc:
            return CollectReviewResponse(
                run=None, reason=f"the run could not be read: {exc}"
            )
        if run.outcome == "running":
            # The run is not finished, or was asked for another answer.
            # Nothing is stored or recorded yet. The entry's id is made
            # from the workflow run and the agent, so only the first
            # entry written would count, and it must say how the run
            # ended.
            return CollectReviewResponse(
                run=run, reason="the run has not finished"
            )
        # The write-up is stored before the entry that gives its key,
        # so that a key in the journal always leads to a write-up.
        kept = self._stored(request, run)
        self._journal.append(
            [
                Recorder(
                    request.ref,
                    request.correlation,
                    request.corpus_version or None,
                    self._clock.now(),
                ).entry(
                    AGENT_DISPATCHED,
                    f"{request.agent_id}/collected",
                    {
                        "agent_id": request.agent_id,
                        "step": "collected",
                        "outcome": run.outcome,
                        "runner": run.runner,
                        "fingerprint": run.fingerprint,
                        "cost": run.cost,
                        "events": len(run.transcript),
                        "detail": run.detail,
                        **kept,
                    },
                    commit_sha=request.head_sha,
                    agent_id=request.agent_id,
                )
            ]
        )
        if run.outcome not in ANSWERED:
            said = run.outcome.replace("_", " ")
            return CollectReviewResponse(
                run=run, reason=f"the run {said}: {run.detail}"
            )
        return CollectReviewResponse(run=run)

    def _stored(
        self, request: CollectReviewRequest, run: Run
    ) -> dict[str, Any]:
        """Store the run's write-up, and return what to add to the
        journal entry.

        Returns nothing to add if there is no write-up or nowhere to
        store it. Returns a key of None if the store refused: the run's
        outcome and cost are still recorded.
        """
        text = run.artifact.get("write_up")
        write_up = WriteUp(
            correlation=request.correlation,
            agent_id=request.agent_id,
            text=text if isinstance(text, str) else "",
        )
        if self._write_ups is None or not write_up.is_prose:
            return {}
        try:
            return {"write_up_id": self._write_ups.put(write_up)}
        except Exception:
            return {"write_up_id": None}
