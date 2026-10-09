"""Ask a runner which finished runs it still holds, and store the
write-ups of those it does.

Some runners keep a run after it has finished, for a time. The journal
has an entry for every dispatch. This use case goes through those
entries, asks the runner for each run, and reports what came back.

It can be set up in two ways:

- With a write-up keeper, a journal and a clock. Each write-up found is
  stored, and a fact is written to the journal that gives the key it is
  stored under.
- With none of the three. Nothing is stored or recorded, and the
  response has the same counts. This is a way to see what would be
  found.

It never dispatches anything. Running a task again would produce a
different write-up, so a write-up the runner no longer holds cannot be
got back.
"""

from dataclasses import dataclass
from datetime import datetime

from bugflow.shared.domain.models.journal_entry import JournalEntry, event_id
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.work.domain.errors import (
    AgentUnavailableError,
    WriteUpNotKeptError,
)
from bugflow.work.domain.facts import AGENT_DISPATCHED
from bugflow.work.domain.models.agent import AgentRun
from bugflow.work.domain.models.journal import DispatchedWork
from bugflow.work.domain.services.delegated_work import DelegatedWorkService
from bugflow.work.domain.services.dispatch_record import DispatchRecordService
from bugflow.work.domain.services.write_up_keeper import WriteUpKeeperService
from bugflow.work.dtos.probe_retained_write_ups import (
    Outcome,
    Probe,
    ProbeRetainedWriteUpsRequest,
    ProbeRetainedWriteUpsResponse,
)


@dataclass(frozen=True, kw_only=True)
class _Keeping:
    """The three things needed to store a write-up and record that it
    was stored."""

    keeper: WriteUpKeeperService
    journal: RecordingService
    clock: ClockService


class ProbeRetainedWriteUpsUseCase:
    def __init__(
        self,
        dispatches: DispatchRecordService,
        agent: DelegatedWorkService,
        keeper: WriteUpKeeperService | None = None,
        journal: RecordingService | None = None,
        clock: ClockService | None = None,
    ) -> None:
        """Give ``keeper``, ``journal`` and ``clock`` together to have
        write-ups stored, or none of them to only report. Raises
        ``ValueError`` if some are given and others not."""
        wired = (keeper, journal, clock)
        if any(part is not None for part in wired) and not all(
            part is not None for part in wired
        ):
            raise ValueError(
                "storing a write-up needs a keeper, a journal and a "
                "clock; give all three or none"
            )
        self._dispatches = dispatches
        self._agent = agent
        self._keeping = (
            _Keeping(keeper=keeper, journal=journal, clock=clock)
            if keeper is not None and journal is not None and clock is not None
            else None
        )

    def execute(
        self, request: ProbeRetainedWriteUpsRequest
    ) -> ProbeRetainedWriteUpsResponse:
        """Ask about each recorded dispatch, oldest first, and return
        what was found for each."""
        dispatched = self._dispatches.dispatched_work()
        if request.limit > 0:
            dispatched = dispatched[: request.limit]
        return ProbeRetainedWriteUpsResponse(
            runner=self._agent.runner,
            probes=tuple(self._probe(work) for work in dispatched),
        )

    def _probe(self, work: DispatchedWork) -> Probe:
        handle = work.handle
        if not handle.remote_id:
            return self._line(
                work, "no_remote_id", "the record gives no remote id"
            )
        if handle.runner != self._agent.runner:
            return self._line(
                work,
                "other_runner",
                f"dispatched to {handle.runner or 'no runner'}",
            )
        try:
            run = self._agent.collect(handle)
        except AgentUnavailableError as exc:
            return self._line(work, "unreachable", str(exc))
        text = str(run.artifact.get("write_up") or "")
        if not text.strip():
            return self._line(work, "no_write_up", run.detail or run.outcome)
        if self._keeping is None:
            return self._line(
                work, "write_up", run.detail, characters=len(text.strip())
            )
        return self._keep(self._keeping, work, run, text)

    def _keep(
        self,
        keeping: _Keeping,
        work: DispatchedWork,
        run: AgentRun,
        text: str,
    ) -> Probe:
        """Store the write-up, then write the fact that gives its key.

        The write-up is stored first. If the process stops between the
        two steps, a write-up is stored that no fact refers to. The
        next time, it is stored again under the same key, which changes
        nothing, and the fact is written.
        """
        characters = len(text.strip())
        try:
            write_up_id = keeping.keeper.keep(
                work.correlation, work.agent_id, text
            )
        except WriteUpNotKeptError as exc:
            return self._line(
                work, "not_kept", str(exc), characters=characters
            )
        keeping.journal.append(
            [self._recovered(work, run, write_up_id, keeping.clock.now())]
        )
        return self._line(
            work,
            "kept",
            run.detail,
            characters=characters,
            write_up_id=write_up_id,
        )

    def _recovered(
        self,
        work: DispatchedWork,
        run: AgentRun,
        write_up_id: str,
        occurred_at: datetime,
    ) -> JournalEntry:
        """The fact that a write-up was found and stored.

        It is a new entry, with the step "recovered". Entries in the
        journal are never changed, so the earlier entries about the run
        stay as they were written.

        Its id is made from the workflow run and the agent. Storing the
        write-up of the same run a second time writes no second entry.
        """
        return JournalEntry(
            event_id=event_id(
                work.correlation,
                AGENT_DISPATCHED,
                f"{work.agent_id}/recovered",
            ),
            occurred_at=occurred_at,
            event_type=AGENT_DISPATCHED,
            forge=work.forge,
            repo=work.repo,
            pr_number=work.pr_number,
            commit_sha=work.commit_sha,
            corpus_version=work.corpus_version,
            workflow_id=work.correlation.workflow_id,
            run_id=work.correlation.run_id,
            agent_id=work.agent_id,
            payload={
                "agent_id": work.agent_id,
                "step": "recovered",
                "runner": work.handle.runner,
                "remote_id": work.handle.remote_id,
                "write_up_id": write_up_id,
                "outcome": run.outcome,
                "dispatched_at": work.occurred_at.isoformat(),
            },
        )

    def _line(
        self,
        work: DispatchedWork,
        outcome: Outcome,
        detail: str = "",
        characters: int = 0,
        write_up_id: str = "",
    ) -> Probe:
        return Probe(
            occurred_at=work.occurred_at,
            repo=work.repo,
            pr_number=work.pr_number,
            agent_id=work.agent_id,
            remote_id=work.handle.remote_id,
            runner=work.handle.runner,
            outcome=outcome,
            detail=detail,
            characters=characters,
            write_up_id=write_up_id,
        )
