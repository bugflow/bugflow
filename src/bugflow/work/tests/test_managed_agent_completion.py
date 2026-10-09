"""Tests of ``completion_from_managed_agent``: which webhook events are
completions."""

from typing import Any

from bugflow.work.infrastructure.managed_agent import RUNNER
from bugflow.work.infrastructure.managed_agent_completion import (
    completion_from_managed_agent,
)


class Thing:
    """An object with the given attributes, like one the SDK returns."""

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


def event(kind: str, session_id: str = "session_1") -> Thing:
    return Thing(data=Thing(type=kind, id=session_id))


def test_a_session_that_went_idle_is_a_completion() -> None:
    completion = completion_from_managed_agent(event("session.status_idled"))

    assert completion is not None
    assert (completion.runner, completion.remote_id) == (RUNNER, "session_1")


def test_a_session_that_was_terminated_is_a_completion() -> None:
    completion = completion_from_managed_agent(
        event("session.status_terminated")
    )

    assert completion is not None
    assert completion.remote_id == "session_1"


def test_a_session_that_started_running_is_not_a_completion() -> None:
    started = event("session.status_run_started")

    assert completion_from_managed_agent(started) is None


def test_an_event_about_something_else_is_not_a_completion() -> None:
    assert completion_from_managed_agent(event("vault.created")) is None


def test_an_event_with_no_session_id_is_not_a_completion() -> None:
    nameless = event("session.status_idled", "")

    assert completion_from_managed_agent(nameless) is None
