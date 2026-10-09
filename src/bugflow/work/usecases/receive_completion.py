"""Receive a completion: a runner's message that one of its runs has
finished.

A completion names only the runner and the runner's name for the work.
The use case looks in the journal for the dispatch of that work, which
says which workflow run started it and for which agent. It then passes
the completion to that workflow run.

The workflow run is always the one the journal names. A completion
cannot choose which workflow run is told.

Every completion is written to the journal, whatever happened to it.
So when a workflow run waited for a completion and none seemed to come,
the journal shows which of three things happened: one arrived after the
workflow run had ended, one arrived for work the journal does not know,
or none arrived.
"""

from bugflow.shared.domain.models.journal_entry import JournalEntry, event_id
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.work.domain.facts import COMPLETION_RECEIVED
from bugflow.work.domain.models.journal import DispatchedRun
from bugflow.work.domain.services.completion_handler import CompletionHandler
from bugflow.work.domain.services.journal import JournalService
from bugflow.work.dtos.receive_completion import (
    Outcome,
    ReceiveCompletionRequest,
    ReceiveCompletionResponse,
)


class ReceiveCompletionUseCase:
    def __init__(
        self,
        journal: JournalService,
        handler: CompletionHandler,
        recording: RecordingService,
        clock: ClockService,
    ) -> None:
        self._journal = journal
        self._handler = handler
        self._recording = recording
        self._clock = clock

    def execute(
        self, request: ReceiveCompletionRequest
    ) -> ReceiveCompletionResponse:
        """Pass the completion on, record it, and say what happened."""
        completion = request.completion
        found = self._journal.dispatched_run(
            completion.runner, completion.remote_id
        )
        if found is None:
            return self._recorded(
                request,
                None,
                "unknown",
                f"no dispatch recorded for {completion.remote_id}",
            )
        acknowledged = self._handler.handle_completion(
            found.correlation, found.agent_id, completion.remote_id
        )
        if not acknowledged.will_comply:
            return self._recorded(
                request,
                found,
                "not_waiting",
                "the workflow run is no longer waiting for this run",
            )
        return self._recorded(request, found, "signalled", "")

    def _recorded(
        self,
        request: ReceiveCompletionRequest,
        found: DispatchedRun | None,
        outcome: Outcome,
        reason: str,
    ) -> ReceiveCompletionResponse:
        """Write the completion to the journal and build the response.

        A completion for unknown work belongs to no workflow run. It is
        recorded with an empty workflow id and run id.

        The entry's id is made from the workflow run, the runner and the
        runner's name for the work. A completion that is sent twice is
        recorded once.
        """
        completion = request.completion
        correlation = (
            found.correlation
            if found
            else Correlation(workflow_id="", run_id="")
        )
        self._recording.append(
            [
                JournalEntry(
                    event_id=event_id(
                        correlation,
                        COMPLETION_RECEIVED,
                        f"{completion.runner}/{completion.remote_id}",
                    ),
                    occurred_at=self._clock.now(),
                    event_type=COMPLETION_RECEIVED,
                    forge=found.forge if found else "",
                    repo=found.repo if found else "",
                    pr_number=found.pr_number if found else None,
                    commit_sha=found.commit_sha if found else None,
                    corpus_version=None,
                    workflow_id=correlation.workflow_id,
                    run_id=correlation.run_id,
                    agent_id=found.agent_id if found else None,
                    payload={
                        "runner": completion.runner,
                        "remote_id": completion.remote_id,
                        "outcome": outcome,
                        "reason": reason,
                    },
                )
            ]
        )
        return ReceiveCompletionResponse(outcome=outcome, reason=reason)
