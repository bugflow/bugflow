"""An adapter from the review context's delegated work interface to the
work context's.

The work context has ``AgentTask``, ``AgentHandle`` and ``AgentRun``. The
review context has ``Task``, ``Handle`` and ``Run``. The two agree field
for field, so a workflow history recorded with one still reads with the
other, and this adapter only renames what it carries.
"""

from typing import cast

from bugflow.review.domain.errors import (
    AgentTemporarilyUnavailableError,
    AgentUnavailableError,
)
from bugflow.review.domain.models.delegation import Handle, Run, RunParty, Task
from bugflow.work.domain.errors import (
    AgentTemporarilyUnavailableError as WorkAgentTemporarilyUnavailableError,
)
from bugflow.work.domain.errors import (
    AgentUnavailableError as WorkAgentUnavailableError,
)
from bugflow.work.domain.models.agent import (
    AgentHandle,
    AgentRun,
    AgentTask,
    Assurance,
    Party,
    PartyKind,
    PartyRole,
)
from bugflow.work.domain.services.delegated_work import DelegatedWorkService


def _task(task: Task) -> AgentTask:
    return AgentTask(
        instructions=task.instructions,
        inputs=task.inputs,
        repository=task.repository,
        commit=task.commit,
        head=task.head,
        artifact_schema=task.artifact_schema,
        budget=task.budget,
        attempts=task.attempts,
    )


def _handle(handle: AgentHandle) -> Handle:
    return Handle(
        runner=handle.runner,
        fingerprint=handle.fingerprint,
        remote_id=handle.remote_id,
        run=_run(handle.run) if handle.run is not None else None,
        budget=handle.budget,
        artifact_schema=handle.artifact_schema,
        attempts=handle.attempts,
        patience=handle.patience,
    )


def _work_handle(handle: Handle) -> AgentHandle:
    return AgentHandle(
        runner=handle.runner,
        fingerprint=handle.fingerprint,
        remote_id=handle.remote_id,
        run=_work_run(handle.run) if handle.run is not None else None,
        budget=handle.budget,
        artifact_schema=handle.artifact_schema,
        attempts=handle.attempts,
        patience=handle.patience,
    )


def _run(run: AgentRun) -> Run:
    return Run(
        outcome=run.outcome,
        artifact=run.artifact,
        transcript=run.transcript,
        cost=run.cost,
        runner=run.runner,
        fingerprint=run.fingerprint,
        detail=run.detail,
        parties=tuple(
            RunParty(
                kind=one.kind,
                role=one.role,
                identified_as=one.identified_as,
                assurance=one.assurance,
            )
            for one in run.parties
        ),
        accountable=run.accountable,
        workings=run.workings,
        decision=run.decision,
        proposals=run.proposals,
    )


def _unavailable(exc: WorkAgentUnavailableError) -> AgentUnavailableError:
    """Turn the work context's error into the review context's, with
    ``retry_after`` if the error carries one."""
    if isinstance(exc, WorkAgentTemporarilyUnavailableError):
        return AgentTemporarilyUnavailableError(
            str(exc), retry_after=exc.retry_after
        )
    return AgentUnavailableError(str(exc))


def _work_run(run: Run) -> AgentRun:
    return AgentRun(
        outcome=run.outcome,
        artifact=run.artifact,
        transcript=run.transcript,
        cost=run.cost,
        runner=run.runner,
        fingerprint=run.fingerprint,
        detail=run.detail,
        parties=tuple(
            Party(
                kind=cast("PartyKind", one.kind),
                role=cast("PartyRole", one.role),
                identified_as=one.identified_as,
                assurance=cast("Assurance", one.assurance),
            )
            for one in run.parties
        ),
        accountable=run.accountable,
        workings=run.workings,
        decision=run.decision,
        proposals=run.proposals,
    )


class WorkDelegation:
    """Implements the review context's ``DelegatedWorkService`` with the
    work context's."""

    def __init__(self, agent: DelegatedWorkService) -> None:
        self._agent = agent

    @property
    def runner(self) -> str:
        return self._agent.runner

    @property
    def fingerprint(self) -> str:
        return self._agent.fingerprint

    def dispatch(self, task: Task) -> Handle:
        try:
            return _handle(self._agent.dispatch(_task(task)))
        except WorkAgentUnavailableError as exc:
            raise _unavailable(exc) from exc

    @property
    def notifies(self) -> bool:
        return self._agent.notifies

    def wait(self, handle: Handle, patience: float) -> bool:
        try:
            return self._agent.wait(_work_handle(handle), patience)
        except WorkAgentUnavailableError as exc:
            raise _unavailable(exc) from exc

    def collect(self, handle: Handle) -> Run:
        try:
            return _run(self._agent.collect(_work_handle(handle)))
        except WorkAgentUnavailableError as exc:
            raise _unavailable(exc) from exc

    def stop(self, handle: Handle) -> None:
        self._agent.stop(_work_handle(handle))
