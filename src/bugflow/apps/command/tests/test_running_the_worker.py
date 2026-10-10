"""Tests of ``bugflow worker``, run by its command line. No Temporal
server is reached: the worker is refused before it connects, or stood
in for."""

import asyncio
import subprocess
import sys
from collections.abc import Mapping

import pytest

from bugflow.apps.command.command import run
from bugflow.apps.shared.temporal import TemporalUnavailableError
from bugflow.apps.worker import worker

TEMPORAL = {"TEMPORAL_ADDRESS": "nowhere:7233", "TEMPORAL_TASK_QUEUE": "q"}


def test_no_temporal_server_named_is_an_error_before_anything_runs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["worker"], environ={}) == 2
    assert "TEMPORAL_ADDRESS and TEMPORAL_TASK_QUEUE are required" in (
        capsys.readouterr().err
    )


def test_a_worker_with_nothing_to_do_says_what_is_not_set(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["worker"], environ=TEMPORAL) == 2
    said = capsys.readouterr().err
    assert "error: the worker has nothing to do" in said
    assert "reviews nothing: DATABASE_URL is not set" in said


def test_the_subcommand_runs_the_worker_with_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[Mapping[str, str]] = []

    async def stand_in(environ: Mapping[str, str]) -> None:
        await asyncio.sleep(0)
        ran.append(environ)

    monkeypatch.setattr(worker, "run", stand_in)

    assert run(["worker"], environ=TEMPORAL) == 0
    assert ran == [TEMPORAL]


def test_a_temporal_server_that_cannot_be_reached_is_an_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def unreachable(environ: Mapping[str, str]) -> None:
        raise TemporalUnavailableError("could not reach Temporal at nowhere")

    monkeypatch.setattr(worker, "run", unreachable)

    assert run(["worker"], environ=TEMPORAL) == 2
    assert "could not reach Temporal" in capsys.readouterr().err


def test_the_worker_still_runs_as_a_module() -> None:
    ran = subprocess.run(
        [sys.executable, "-m", "bugflow.apps.worker"],
        env={},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert ran.returncode != 0
    assert "TEMPORAL_ADDRESS and TEMPORAL_TASK_QUEUE are required" in (
        ran.stderr
    )
