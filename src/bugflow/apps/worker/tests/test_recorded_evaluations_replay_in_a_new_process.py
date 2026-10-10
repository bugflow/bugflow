"""Tests that a recorded evaluation replays in a process that imports
as the worker does, and that every model a workflow carries is built
when it is imported.

A model whose schema is built lazily can be met unbuilt inside the
workflow sandbox, where serialising it fails. The other tests import
every model before any workflow runs and so cannot see that. These hold
the two conditions it needs.
"""

import importlib
import inspect
import pkgutil
import subprocess
import sys
from pathlib import Path

import pydantic

import bugflow

HISTORIES = Path(__file__).parent / "histories"

REPLAY = """
import asyncio, sys
from pathlib import Path
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer
from bugflow.apps.worker.worker import workflow_runner
from bugflow.apps.worker.evaluate_pull_request import (
    EvaluatePullRequestWorkflow,
)

for path in sys.argv[1:]:
    asyncio.run(
        Replayer(
            workflows=[EvaluatePullRequestWorkflow],
            data_converter=pydantic_data_converter,
            workflow_runner=workflow_runner(),
        ).replay_workflow(
            WorkflowHistory.from_json("recorded", Path(path).read_text())
        )
    )
"""


def test_every_request_and_response_is_built_when_imported() -> None:
    unbuilt = [
        f"{module.name}.{name}"
        for module in pkgutil.walk_packages(bugflow.__path__, "bugflow.")
        if ".dtos." in module.name
        for name, model in vars(importlib.import_module(module.name)).items()
        if inspect.isclass(model)
        and issubclass(model, pydantic.BaseModel)
        and model.__module__ == module.name
        and not model.__pydantic_complete__
    ]
    assert not unbuilt, (
        f"Built lazily, so a sandbox may meet it unbuilt: {unbuilt}"
    )


def test_recorded_evaluations_replay_as_a_restarted_worker() -> None:
    histories = sorted(HISTORIES.glob("evaluate_pull_request*.json"))
    assert histories
    replayed = subprocess.run(
        [sys.executable, "-c", REPLAY, *map(str, histories)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert replayed.returncode == 0, replayed.stderr[-2000:]
