"""Tests of ``StubAgent``, the runner that does no work."""

from bugflow.work.domain.models.agent import AgentHandle, AgentTask
from bugflow.work.domain.services.delegated_work import DelegatedWorkService
from bugflow.work.infrastructure.stub_agent import RUNNER, StubAgent

TASK = AgentTask(instructions="Read the files and report what you find.")


def test_the_stub_is_a_runner() -> None:
    runner: DelegatedWorkService = StubAgent()
    assert runner.runner == RUNNER
    assert len(runner.fingerprint) == 12
    assert not runner.notifies


def test_a_task_given_to_the_stub_ends_at_once_as_declined() -> None:
    stub = StubAgent()

    handle = stub.dispatch(TASK)

    assert handle.is_finished
    assert handle.remote_id == ""
    assert stub.wait(handle, patience=60.0)
    run = stub.collect(handle)
    assert run.outcome == "declined"
    assert (run.runner, run.artifact) == (RUNNER, {})
    assert "no runner is configured" in run.detail


def test_stopping_a_stub_run_does_nothing() -> None:
    stub = StubAgent()
    handle = stub.dispatch(TASK)

    stub.stop(handle)
    stub.stop(handle)

    assert stub.collect(handle).outcome == "declined"


def test_a_handle_with_no_run_in_it_is_collected_as_failed() -> None:
    handle = AgentHandle(runner=RUNNER, fingerprint="f")

    assert StubAgent().collect(handle).outcome == "failed"
