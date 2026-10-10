"""What a workflow is started with, when a repository declared a window.

An event cadence is bounded by the window its signals settle in, and that
window is the repository's to declare. The workflow takes the figure from
its input; the starter is what sets it.
"""

import asyncio
from typing import Any

from bugflow.apps.ingress.ingress import worker_workflows
from bugflow.apps.shared.temporal import (
    TemporalEvaluationStarter,
    TemporalSettings,
)
from bugflow.apps.worker.pull_request import DEBOUNCE, PullRequestWorkflow
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="o", repo="r", number=7)
SETTINGS = TemporalSettings.from_environment({})


class FakeHandle:
    id = "pr/github/o/r/7"
    result_run_id = "run-1"


class FakeClient:
    """A Temporal client that remembers what it was asked to start."""

    def __init__(self) -> None:
        self.started: list[tuple[Any, Any, dict[str, Any]]] = []

    async def start_workflow(
        self, run: Any, arg: Any, **kwargs: Any
    ) -> FakeHandle:
        self.started.append((run, arg, kwargs))
        return FakeHandle()


def started_with(settling: float | None, told: bool = True) -> Any:
    client = FakeClient()
    loop = asyncio.new_event_loop()
    try:
        starter = TemporalEvaluationStarter(
            client,  # type: ignore[arg-type]
            SETTINGS,
            loop,
            worker_workflows(),
            (lambda forge, repo: settling) if told else None,
        )
        loop.run_until_complete(starter._start(REF, "d-1"))
    finally:
        loop.close()
    (started,) = client.started
    return started


def test_a_declared_window_is_what_the_workflow_waits() -> None:
    _, input, _ = started_with(300.0)
    assert input.debounce_seconds == 300.0


def test_a_repository_that_declared_none_waits_the_default() -> None:
    """Which is what every run already in flight waits."""
    _, input, _ = started_with(None)
    assert input.debounce_seconds == DEBOUNCE.total_seconds()


def test_a_starter_told_nothing_waits_the_default() -> None:
    """A deployment with no boundaries reachable is not thereby a
    deployment that evaluates every push separately."""
    _, input, _ = started_with(None, told=False)
    assert input.debounce_seconds == DEBOUNCE.total_seconds()


def test_the_delivery_is_signalled_to_the_pull_requests_workflow() -> None:
    run, input, kwargs = started_with(None)
    assert run == PullRequestWorkflow.run
    assert input.ref == REF
    assert kwargs["id"] == "pr/github/o/r/7"
    assert kwargs["task_queue"] == SETTINGS.task_queue
    assert (kwargs["start_signal"], kwargs["start_signal_args"]) == (
        "delivery",
        ["d-1"],
    )
