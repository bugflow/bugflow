"""The Temporal client the programs share, and the starter that hands a
pull request's deliveries to its workflow.

Neither runs a workflow. The worker polls the task queue and runs them,
with the forge, the reviewers and the judge composed in its own
environment.

The starter signals the worker's workflows by name, and those names are
the worker's. What programs share imports no program, so the program
that composes a starter passes the names in, as ``WorkerWorkflows``.
"""

import asyncio
from collections.abc import Callable, Coroutine, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from temporalio.client import (
    Client,
    Interceptor,
    WorkflowExecutionDescription,
    WorkflowExecutionStatus,
)
from temporalio.common import WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.service import RPCError, RPCStatusCode

from bugflow.forge.domain.errors import EvaluationStartError
from bugflow.review.dtos.wait_review import WaitReviewResponse
from bugflow.shared.domain.values.acknowledgement import Acknowledgement
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

#: The task queue the programs use when ``TEMPORAL_TASK_QUEUE`` is unset.
DEFAULT_TASK_QUEUE = "bugflow"

#: How long a call waits for Temporal before the delivery is refused and
#: the forge told to send it again.
CALL_TIMEOUT_SECONDS = 30


class TemporalUnavailableError(Exception):
    """Temporal could not be reached."""


@dataclass(frozen=True)
class TemporalSettings:
    """Where Temporal is, and which queue the worker listens on."""

    address: str
    namespace: str
    task_queue: str
    ui_url: str

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str]
    ) -> "TemporalSettings":
        """Read ``TEMPORAL_ADDRESS``, ``TEMPORAL_NAMESPACE``,
        ``TEMPORAL_TASK_QUEUE`` and ``TEMPORAL_UI_URL``, each with a
        default for a server on the same host."""
        return cls(
            address=environ.get("TEMPORAL_ADDRESS") or "localhost:7233",
            namespace=environ.get("TEMPORAL_NAMESPACE") or "default",
            task_queue=environ.get("TEMPORAL_TASK_QUEUE")
            or DEFAULT_TASK_QUEUE,
            ui_url=environ.get("TEMPORAL_UI_URL") or "http://localhost:8080",
        )

    def history_url(self, workflow_id: str, run_id: str) -> str:
        """The address of a run's history in Temporal's own web UI."""
        return (
            f"{self.ui_url}/namespaces/{self.namespace}/workflows/"
            f"{quote(workflow_id, safe='')}/{run_id}/history"
        )


async def connect(
    settings: TemporalSettings, interceptors: Sequence[Interceptor] = ()
) -> Client:
    """Connect to Temporal, or raise ``TemporalUnavailableError``.

    ``interceptors`` are the client's, for a program that traces what it
    starts.
    """
    try:
        return await Client.connect(
            settings.address,
            namespace=settings.namespace,
            data_converter=pydantic_data_converter,
            interceptors=list(interceptors),
        )
    except Exception as exc:
        raise TemporalUnavailableError(
            f"could not reach Temporal at {settings.address}"
        ) from exc


@dataclass(frozen=True, kw_only=True)
class WorkerWorkflows:
    """What the starter needs to know of the worker's workflows.

    The worker defines them; the program that composes a starter reads
    them from the worker and passes them here.
    """

    #: The pull request workflow's run method, or its registered name.
    pull_request: Any
    #: What the pull request workflow is started with, for a pull request
    #: and the seconds a burst of its deliveries settles for, or None to
    #: leave the workflow its default.
    input_for: Callable[[PullRequestRef, float | None], Any]
    #: The id of a pull request's workflow.
    workflow_id_for: Callable[[PullRequestRef], str]
    #: The signals a delivery and a close arrive as.
    delivery_signal: str
    close_signal: str
    #: The evaluation workflow's signal that a runner has finished a run.
    review_complete_signal: str
    #: Pick out, from a workflow's open activity ids, the waits for one
    #: agent's run.
    waits_of: Callable[[Iterable[str], str, str], Iterable[str]]


class TemporalEvaluationStarter:
    """Hands deliveries to each pull request's workflow; the worker runs
    it. Implements the forge's ``EvaluationStarterPort`` and the work
    context's ``CompletionHandler``.

    The receive-delivery use case is synchronous and runs on a worker
    thread, so each call is scheduled onto the event loop that owns the
    Temporal client.
    """

    def __init__(
        self,
        client: Client,
        settings: TemporalSettings,
        loop: asyncio.AbstractEventLoop,
        workflows: WorkerWorkflows,
        settling: Callable[[str, str], float | None] | None = None,
    ) -> None:
        self._client = client
        self._settings = settings
        self._loop = loop
        self._workflows = workflows
        # How long a burst of deliveries settles for, as the repository
        # declared it. None where it declared none, and then the
        # workflow waits its own default, which is what every run already
        # in flight waits.
        self._settling = settling or (lambda forge, repo: None)

    def start(self, ref: PullRequestRef, delivery_id: str) -> Correlation:
        return self._run(
            self._start(ref, delivery_id),
            f"hand the delivery for {ref} to Temporal",
        )

    def close(
        self, ref: PullRequestRef, delivery_id: str, merged: bool = False
    ) -> Correlation | None:
        return self._run(
            self._close(ref, delivery_id, merged),
            f"hand the delivery for {ref} to Temporal",
        )

    def handle_completion(
        self, correlation: Correlation, agent_id: str, remote_id: str
    ) -> Acknowledgement:
        signalled = self._run(
            self._complete(correlation, agent_id, remote_id),
            f"signal {agent_id}'s review complete",
        )
        if not signalled:
            return Acknowledgement.unable("no evaluation was waiting")
        return Acknowledgement.wilco()

    def _run[T](self, coroutine: Coroutine[Any, Any, T], what: str) -> T:
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout=CALL_TIMEOUT_SECONDS)
        except Exception as exc:
            raise EvaluationStartError(f"could not {what}: {exc}") from exc

    async def _start(
        self, ref: PullRequestRef, delivery_id: str
    ) -> Correlation:
        # Signal-with-start: signals the running workflow, or starts one.
        settling = self._settling(ref.forge, f"{ref.owner}/{ref.repo}")
        handle = await self._client.start_workflow(
            self._workflows.pull_request,
            self._workflows.input_for(ref, settling),
            id=self._workflows.workflow_id_for(ref),
            task_queue=self._settings.task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            start_signal=self._workflows.delivery_signal,
            start_signal_args=[delivery_id],
        )
        if handle.result_run_id is None:
            raise EvaluationStartError("Temporal returned no run id")
        return Correlation(workflow_id=handle.id, run_id=handle.result_run_id)

    async def _close(
        self, ref: PullRequestRef, delivery_id: str, merged: bool
    ) -> Correlation | None:
        handle = self._client.get_workflow_handle(
            self._workflows.workflow_id_for(ref)
        )
        try:
            description = await handle.describe()
            if description.status != WorkflowExecutionStatus.RUNNING:
                return None
            await handle.signal(
                self._workflows.close_signal, args=[delivery_id, merged]
            )
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                return None
            raise
        return Correlation(workflow_id=handle.id, run_id=description.run_id)

    async def _complete(
        self, correlation: Correlation, agent_id: str, remote_id: str
    ) -> bool:
        """End the wait this run is in, and signal as well.

        The wait is an activity the worker handed over, named after the
        agent and the remote id so that this, which knows both from the
        dispatch row, can find it without anything having been kept. The
        signal stays beside it for a run that started before the wait
        was named.
        """
        handle = self._client.get_workflow_handle(
            correlation.workflow_id, run_id=correlation.run_id
        )
        try:
            description = await handle.describe()
            if description.status != WorkflowExecutionStatus.RUNNING:
                return False
            await self._end_the_wait(
                description, correlation, agent_id, remote_id
            )
            await handle.signal(
                self._workflows.review_complete_signal,
                args=[agent_id, remote_id],
            )
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                return False
            raise
        return True

    async def _end_the_wait(
        self,
        description: WorkflowExecutionDescription,
        correlation: Correlation,
        agent_id: str,
        remote_id: str,
    ) -> None:
        """Finish the open wait for this run, if the worker handed one
        over. A run whose worker waits by asking has none, and one that
        has already been ended answers NOT_FOUND, which is what a
        completion arriving twice looks like."""
        for one in self._workflows.waits_of(
            (
                pending.activity_id
                for pending in description.raw_description.pending_activities
            ),
            agent_id,
            remote_id,
        ):
            try:
                await self._client.get_async_activity_handle(
                    workflow_id=correlation.workflow_id,
                    run_id=correlation.run_id,
                    activity_id=one,
                ).complete(WaitReviewResponse(ready=True))
            except RPCError as exc:
                if exc.status != RPCStatusCode.NOT_FOUND:
                    raise
