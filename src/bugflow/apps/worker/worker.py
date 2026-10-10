"""The worker program.

It connects to a Temporal server and runs the workflows and activities
it is assembled from. This package gives it two parts: keeping the
archive's search index up to date (``archive_index.py``), and reviewing
pull requests under the policy deployment in force (``review.py``). A
program built on this package adds parts of its own and calls ``run``
with the sum.

Run it with ``bugflow worker`` or ``python -m bugflow.apps.worker``.

The worker reads the database's tables and does not make them.
``bugflow migrate`` runs the scripts that do.
"""

import asyncio
import os
import signal
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field

from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import (
    SandboxedWorkflowRunner,
    SandboxRestrictions,
)

from bugflow.apps.shared.temporal import TemporalSettings, connect
from bugflow.apps.worker import archive_index, review
from bugflow.apps.worker.evaluate_pull_request import (
    judge_task_queue,
    queue_for,
)
from bugflow.apps.worker.litellm_judge import MODEL_CLASS_VARIABLES
from bugflow.apps.worker.parts import WorkerParts

__all__ = [
    "ACTIVITY_THREADS",
    "JudgeRates",
    "WorkerParts",
    "main",
    "parts_from_environment",
    "run",
    "workflow_runner",
]

#: How many activities may run at the same time. Activities here are
#: ordinary blocking functions, so each runs on a thread.
ACTIVITY_THREADS = 8

#: The setting that gives the rate every rate-limited queue allows
#: unless a class has a setting of its own.
RATE_VARIABLE = "JUDGE_REQUESTS_PER_SECOND"

#: The setting that gives each class's rate. Not given, the class takes
#: ``RATE_VARIABLE``'s. Zero is no limit.
CLASS_RATE_VARIABLES = {
    name: f"{RATE_VARIABLE}_{name.upper()}" for name in MODEL_CLASS_VARIABLES
}

#: The rate when ``RATE_VARIABLE`` is not given, in activities a second.
DEFAULT_RATE = 0.2


def workflow_runner() -> SandboxedWorkflowRunner:
    """The sandbox Temporal runs workflow code in, adjusted for pydantic.

    Temporal reloads modules inside the sandbox to catch workflow code
    that is not repeatable. ``pydantic_core`` is a compiled module that
    cannot be reloaded that way, so it is passed through unchanged.
    """
    return SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules(
            "pydantic_core"
        )
    )


@dataclass(frozen=True)
class JudgeRates:
    """What the rate-limited queues allow, across every worker on them.

    A rate is held by the Temporal server for a queue, so it is shared
    by every worker that serves the queue.
    """

    #: Activities a second on the queue that carries the reviews, which
    #: name no class of model.
    reviews: float = DEFAULT_RATE
    #: The same for the queue of each class of model. A quota belongs
    #: to a model, so the limit that protects one is the class's. None
    #: is no limit.
    classes: Mapping[str, float | None] = field(default_factory=dict)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "JudgeRates":
        """Read ``JUDGE_REQUESTS_PER_SECOND`` and each class's own
        setting, named in ``CLASS_RATE_VARIABLES``.

        A class with no setting of its own takes the shared rate. Zero
        is no limit, for a class whose model publishes none.
        """
        shared = float(environ.get(RATE_VARIABLE) or DEFAULT_RATE)
        classes: dict[str, float | None] = {}
        for name, variable in CLASS_RATE_VARIABLES.items():
            said = environ.get(variable, "")
            classes[name] = (float(said) if said else shared) or None
        return cls(reviews=shared, classes=classes)


def parts_from_environment(environ: Mapping[str, str]) -> WorkerParts:
    """Build what this package's worker serves: the archive's search
    index and the review workflows.

    Each part reads its own settings and is empty if they are not
    given, so a worker with no archive still reviews and a worker with
    no deployment in force still indexes. The settings are described in
    ``archive_index.activities_from_environment`` and
    ``review.parts_from_environment``.

    Raises ``ValueError`` if a setting that is given cannot be used.
    """
    return archive_index.parts(environ) + review.parts_from_environment(
        environ
    )


def _rate(rate: float | None) -> str:
    return "no limit" if rate is None else f"{rate} a second"


async def run(
    environ: Mapping[str, str],
    parts: WorkerParts | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Run the worker until it is stopped.

    ``parts`` is what it serves, by default what
    ``parts_from_environment`` builds. ``stop`` is an event that stops
    the worker when it is set. SIGINT and SIGTERM set it, and so may a
    watcher among the parts.

    Three kinds of task queue are served. The task queue runs the
    workflows and ``parts.activities``. The queue beside it, named by
    ``judge_task_queue``, serves ``parts.judging``. One more queue for
    each class of model in ``parts.assessing`` serves that class's
    activities. The last two kinds have a rate limit, which
    ``JudgeRates`` reads. A queue with nothing to serve is not polled.

    Required settings: ``TEMPORAL_ADDRESS`` and ``TEMPORAL_TASK_QUEUE``.
    ``TEMPORAL_NAMESPACE`` defaults to ``default``.

    Raises ``ValueError`` if a required setting is missing, if the
    parts hold nothing to serve and nothing to watch, or if one of
    ``parts.before_serving`` refuses.
    """
    if not (
        environ.get("TEMPORAL_ADDRESS") and environ.get("TEMPORAL_TASK_QUEUE")
    ):
        raise ValueError(
            "TEMPORAL_ADDRESS and TEMPORAL_TASK_QUEUE are required; the "
            "worker does not start without a Temporal server and a task "
            "queue to listen on"
        )
    if parts is None:
        parts = parts_from_environment(environ)
    if not (parts.serves or parts.watchers):
        raise ValueError(
            "the worker has nothing to do: " + "; ".join(parts.lines)
            if parts.lines
            else "the worker has nothing to do"
        )
    settings = TemporalSettings.from_environment(environ)
    rates = JudgeRates.from_environment(environ)
    client = await connect(settings, parts.interceptors)
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        # Only the main thread of a process may take signals. Anywhere
        # else, the caller's event is what stops the worker.
        with suppress(ValueError, RuntimeError, NotImplementedError):
            loop.add_signal_handler(signal_number, stop.set)
    for make in parts.schedules:
        await make(client, settings.task_queue)
    for refuse in parts.before_serving:
        refuse()
    judge_queue = judge_task_queue(settings.task_queue)
    polling = [f"{settings.task_queue} on {settings.address}"]
    with ThreadPoolExecutor(max_workers=ACTIVITY_THREADS) as executor:
        async with AsyncExitStack() as serving:
            if parts.workflows or parts.activities:
                await serving.enter_async_context(
                    Worker(
                        client,
                        task_queue=settings.task_queue,
                        workflows=list(parts.workflows),
                        activities=list(parts.activities),
                        activity_executor=executor,
                        workflow_runner=workflow_runner(),
                    )
                )
            if parts.judging:
                await serving.enter_async_context(
                    Worker(
                        client,
                        task_queue=judge_queue,
                        activities=list(parts.judging),
                        activity_executor=executor,
                        max_task_queue_activities_per_second=rates.reviews,
                    )
                )
                polling.append(f"{judge_queue} at {_rate(rates.reviews)}")
            for name, activities in sorted(parts.assessing.items()):
                if not activities:
                    continue
                queue = queue_for(name, settings.task_queue)
                rate = rates.classes.get(name)
                await serving.enter_async_context(
                    Worker(
                        client,
                        task_queue=queue,
                        activities=list(activities),
                        activity_executor=executor,
                        max_task_queue_activities_per_second=rate,
                    )
                )
                polling.append(f"{queue} at {_rate(rate)}")
            print(f"worker polling {', '.join(polling)}", flush=True)
            for line in parts.lines:
                print(f"worker {line}", flush=True)
            watching: list[asyncio.Future[None]] = [
                asyncio.ensure_future(watch(stop)) for watch in parts.watchers
            ]
            try:
                await stop.wait()
            finally:
                for one in watching:
                    one.cancel()


def main() -> None:
    asyncio.run(run(os.environ))
