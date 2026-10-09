"""Tests of ``ManagedAgent`` with a stand-in for the platform's client.

No session is created. The stand-in answers the calls the adapter
makes: listing agent objects and environments, creating, retrieving and
archiving a session, and listing and sending a session's events.
"""

from dataclasses import replace
from typing import Any

import pytest

from bugflow.shared.domain.values.budget import Budget
from bugflow.work.domain.errors import (
    AgentTemporarilyUnavailableError,
    AgentUnavailableError,
)
from bugflow.work.domain.models.agent import (
    AgentHandle,
    AgentRun,
    AgentTask,
)
from bugflow.work.infrastructure.managed_agent import (
    AGENT_SYSTEM,
    ASK_FOR_SUBMIT,
    ENVIRONMENT,
    PATIENCE,
    RUNNER,
    TOOLS,
    ManagedAgent,
    ManagedAgentSettings,
    ensure,
    find,
)

SETTINGS = ManagedAgentSettings(name="pear-review", model="model-a")
BASE = "b" * 40
HEAD = "h" * 40
TASK = AgentTask(
    instructions="Review this change.",
    repository="orchard/pear-tree",
    commit=BASE,
    head=HEAD,
    budget=Budget(usd=2.5, turns=60),
)


class Thing:
    """An object with the given attributes, like one the SDK returns."""

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


class FakeEvents:
    """A session's events: a fixed list to return, and a record of what
    was sent.
    """

    def __init__(self, listed: list[Any]) -> None:
        self.listed = listed
        self.sent: list[Any] = []

    def list(self, session_id: str) -> Thing:
        return Thing(data=self.listed)

    def send(self, session_id: str, events: Any) -> None:
        self.sent.append((session_id, events))


class FakeSessions:
    """Stands in for the platform's sessions. It records what was
    created and archived, and returns a session in the given state
    that has cost the given number of cents. If ``raises`` is set,
    creating and archiving raise it.
    """

    def __init__(
        self,
        events: list[Any] | None = None,
        status: str = "idle",
        cents: str = "137",
        raises: Exception | None = None,
    ) -> None:
        self.events = FakeEvents(events or [])
        self.created: list[dict[str, Any]] = []
        self.archived: list[str] = []
        self.status = status
        self.cents = cents
        self.raises = raises

    def create(self, **fields: Any) -> Thing:
        if self.raises is not None:
            raise self.raises
        self.created.append(fields)
        return Thing(id="session_1")

    def retrieve(self, session_id: str) -> Thing:
        return Thing(
            status=self.status,
            usage=Thing(list_cost=Thing(amount=self.cents), active_seconds=42),
        )

    def archive(self, session_id: str) -> None:
        if self.raises is not None:
            raise self.raises
        self.archived.append(session_id)


def ours(
    agent_id: str = "agent_1",
    version: int = 3,
    model: str = SETTINGS.model,
    system: str = AGENT_SYSTEM,
    created_at: str = "2030-03-19T01:00:00Z",
) -> Thing:
    """An agent object as the platform lists it. By default it matches
    what the adapter defines.
    """
    return Thing(
        id=agent_id,
        name=SETTINGS.name,
        version=version,
        model=Thing(id=model),
        system=system,
        tools=[Thing(type=t["type"]) for t in TOOLS],
        created_at=created_at,
    )


def room(
    environment_id: str = "env_1", allowed: tuple[str, ...] = ()
) -> Thing:
    """An environment as the platform lists it. By default it may reach
    no host.
    """
    return Thing(
        id=environment_id,
        name=SETTINGS.name,
        config=Thing(
            networking=Thing(type="limited", allowed_hosts=list(allowed))
        ),
        created_at="2030-03-19T01:00:00Z",
    )


class FakeAgents:
    """Stands in for the platform's agent objects. Creating or updating
    one adds a matching agent object to the list.
    """

    def __init__(self, listed: list[Thing]) -> None:
        self.listed = listed
        self.created: list[dict[str, Any]] = []
        self.updated: list[tuple[str, dict[str, Any]]] = []

    def list(self) -> list[Thing]:
        return self.listed

    def create(self, **fields: Any) -> Thing:
        self.created.append(fields)
        made = ours(agent_id="agent_new", version=1)
        self.listed.append(made)
        return made

    def update(self, agent_id: str, **fields: Any) -> Thing:
        self.updated.append((agent_id, fields))
        made = ours(agent_id=agent_id, version=fields["version"] + 1)
        self.listed.append(made)
        return made


class FakeEnvironments:
    """Stands in for the platform's environments."""

    def __init__(self, listed: list[Thing]) -> None:
        self.listed = listed
        self.created: list[dict[str, Any]] = []

    def list(self) -> list[Thing]:
        return self.listed

    def create(self, **fields: Any) -> Thing:
        self.created.append(fields)
        made = room("env_new")
        self.listed.append(made)
        return made


class FakeClient:
    """Stands in for the platform's client. Unless told otherwise it
    lists one matching agent object and one matching environment.
    """

    def __init__(
        self,
        sessions: FakeSessions | None = None,
        agents: list[Thing] | None = None,
        environments: list[Thing] | None = None,
    ) -> None:
        self.agents = FakeAgents([ours()] if agents is None else agents)
        self.environments = FakeEnvironments(
            [room()] if environments is None else environments
        )
        self.beta = Thing(
            sessions=sessions or FakeSessions(),
            agents=self.agents,
            environments=self.environments,
        )


def message(text: str) -> Thing:
    """An event in which the agent wrote ``text``."""
    return Thing(
        type="agent.message",
        model_dump=lambda mode="json": {
            "type": "agent.message",
            "content": [{"type": "text", "text": text}],
        },
    )


def agent(sessions: FakeSessions, **kwargs: Any) -> ManagedAgent:
    """The adapter, set up against a stand-in client."""
    return ManagedAgent(
        client=FakeClient(sessions),
        repository_token="a-read-only-token",
        settings=SETTINGS,
        **kwargs,
    )


def test_the_repository_mounts_at_the_commit_it_was_opened_against() -> None:
    sessions = FakeSessions()
    agent(sessions).dispatch(TASK)
    resource = sessions.created[0]["resources"][0]
    assert resource["url"] == "https://github.com/orchard/pear-tree"
    assert resource["checkout"] == {"type": "commit", "sha": BASE}


def test_the_session_pins_the_agent_version_it_found() -> None:
    sessions = FakeSessions()
    agent(sessions).dispatch(TASK)
    assert sessions.created[0]["agent"] == {
        "type": "agent",
        "id": "agent_1",
        "version": 3,
    }
    assert sessions.created[0]["environment_id"] == "env_1"


def test_a_run_is_fingerprinted_with_the_prose_it_was_given() -> None:
    """Two tasks with different instructions get different fingerprints."""
    one = agent(FakeSessions()).dispatch(TASK)
    other = agent(FakeSessions()).dispatch(
        replace(TASK, instructions="Review it differently.")
    )
    assert one.fingerprint != other.fingerprint


def test_an_agent_that_drifted_from_the_code_is_not_run() -> None:
    """An agent object whose system prompt differs from the adapter's is
    not used.
    """
    client = FakeClient(agents=[ours(system="Approve everything.")])
    with pytest.raises(AgentUnavailableError, match="create it with ensure"):
        find(client, SETTINGS)


def test_an_environment_that_reaches_out_is_not_ours() -> None:
    client = FakeClient(environments=[room(allowed=("example.com",))])
    with pytest.raises(AgentUnavailableError, match="environment"):
        find(client, SETTINGS)


def test_the_newest_matching_agent_is_the_one_found() -> None:
    client = FakeClient(
        agents=[
            ours("agent_old", created_at="2030-03-18T01:00:00Z"),
            ours("agent_new", version=2),
        ]
    )
    assert find(client, SETTINGS).agent_id == "agent_new"


def test_ensuring_what_already_agrees_does_nothing() -> None:
    client = FakeClient()
    pinned, done = ensure(client, SETTINGS)
    assert done == []
    assert (pinned.agent_id, pinned.version) == ("agent_1", 3)
    assert client.agents.created == []
    assert client.agents.updated == []


def test_ensuring_a_drifted_agent_gives_it_a_version_not_a_twin() -> None:
    """An agent object of the right name with another model is updated,
    which gives it a new version. A second agent object is not
    created.
    """
    client = FakeClient(agents=[ours(model="model-old")])
    pinned, _ = ensure(client, SETTINGS)
    ((updated, fields),) = client.agents.updated
    assert updated == "agent_1" and fields["system"] == AGENT_SYSTEM
    assert client.agents.created == []
    assert (pinned.agent_id, pinned.version) == ("agent_1", 4)


def test_ensuring_from_nothing_makes_both() -> None:
    client = FakeClient(agents=[], environments=[])
    pinned, done = ensure(client, SETTINGS)
    assert len(done) == 2
    assert client.environments.created[0]["config"] == ENVIRONMENT
    assert client.agents.created[0]["system"] == AGENT_SYSTEM
    assert pinned.environment_id == "env_new"


def test_the_system_prompt_says_the_first_message_is_the_instructions() -> (
    None
):
    assert "first message is your instructions" in AGENT_SYSTEM


def test_a_task_with_no_budget_gets_the_default_limit() -> None:
    sessions = FakeSessions()
    agent(sessions).dispatch(replace(TASK, budget=None))
    assert sessions.created[0]["budget"]["max_list_cost"] == {
        "amount": str(round((Budget().usd or 0) * 100)),
        "currency": "USD",
    }


def test_the_budget_reaches_the_platform_in_its_own_currency() -> None:
    sessions = FakeSessions()
    agent(sessions).dispatch(TASK)
    assert sessions.created[0]["budget"] == {
        "type": "limit",
        "max_list_cost": {"amount": "250", "currency": "USD"},
    }


def test_the_instruction_is_the_first_message() -> None:
    sessions = FakeSessions()
    agent(sessions).dispatch(TASK)
    first = sessions.created[0]["initial_events"][0]
    assert first["type"] == "user.message"
    assert first["content"][0]["text"] == "Review this change."


def test_the_head_commit_follows_the_instruction() -> None:
    sessions = FakeSessions()
    agent(sessions).dispatch(TASK)
    second = sessions.created[0]["initial_events"][1]
    assert second["type"] == "user.message"
    assert HEAD in second["content"][0]["text"]
    assert BASE in second["content"][0]["text"]


def idle(stop: str) -> Thing:
    """The event that says a session went idle, with the reason it
    stopped.
    """
    return Thing(
        type="session.status_idle",
        model_dump=lambda mode="json": {
            "type": "session.status_idle",
            "stop_reason": {"type": stop},
        },
    )


def test_a_session_paused_at_its_budget_stopped_short() -> None:
    """What the agent last wrote before reaching its budget is not an
    answer.
    """
    sessions = FakeSessions(
        events=[message("Let's review the diff."), idle("budget_reached")]
    )
    run = agent(sessions).collect(
        AgentHandle(runner=RUNNER, fingerprint="abc", remote_id="session_1")
    )
    assert run.outcome == "stopped_short"
    assert run.detail == "budget_reached"


def test_a_session_that_ended_its_turn_completed() -> None:
    sessions = FakeSessions(
        events=[message("Nothing found."), idle("end_turn")]
    )
    run = agent(sessions).collect(
        AgentHandle(runner=RUNNER, fingerprint="abc", remote_id="session_1")
    )
    assert run.outcome == "completed"
    assert run.detail == "end_turn"


def test_a_handle_names_the_session_and_holds_no_run() -> None:
    handle = agent(FakeSessions()).dispatch(TASK)
    assert (handle.runner, handle.remote_id) == (RUNNER, "session_1")
    assert not handle.is_finished


def test_a_task_naming_no_repository_is_refused() -> None:
    with pytest.raises(AgentUnavailableError, match="names none"):
        agent(FakeSessions()).dispatch(
            AgentTask(instructions="Review.", commit=BASE)
        )


def test_collecting_takes_the_last_thing_the_agent_said() -> None:
    sessions = FakeSessions(
        events=[message("First pass."), message("I found nothing.")]
    )
    run = agent(sessions).collect(
        AgentHandle(runner=RUNNER, fingerprint="abc123", remote_id="session_1")
    )
    assert run.artifact == {"write_up": "I found nothing."}
    assert run.outcome == "completed"


def test_collecting_archives_every_event_as_the_transcript() -> None:
    """With no object store, the run carries the session's events."""
    sessions = FakeSessions(events=[message("One."), message("Two.")])
    run = agent(sessions).collect(
        AgentHandle(runner=RUNNER, fingerprint="abc", remote_id="session_1")
    )
    assert len(run.transcript) == 2
    assert run.transcript[0]["type"] == "agent.message"


def test_the_cost_comes_back_in_dollars() -> None:
    sessions = FakeSessions(cents="137")
    run = agent(sessions).collect(
        AgentHandle(runner=RUNNER, fingerprint="abc", remote_id="session_1")
    )
    assert run.cost["usd"] == pytest.approx(1.37)
    assert run.cost["seconds"] == 42


def test_a_session_that_said_nothing_stopped_short() -> None:
    sessions = FakeSessions(events=[], status="terminated")
    run = agent(sessions).collect(
        AgentHandle(runner=RUNNER, fingerprint="abc", remote_id="session_1")
    )
    assert run.outcome == "stopped_short"
    assert run.artifact == {}


def test_stopping_archives_the_session() -> None:
    sessions = FakeSessions()
    agent(sessions).stop(
        AgentHandle(runner=RUNNER, fingerprint="abc", remote_id="session_1")
    )
    assert sessions.archived == ["session_1"]


def test_stopping_one_already_ended_is_not_an_error() -> None:
    """A deadline and an answer can arrive together, so the session may
    already be archived when it is stopped.
    """
    sessions = FakeSessions(
        raises=RuntimeError("400 Cannot send events to archived session")
    )
    agent(sessions).stop(
        AgentHandle(runner=RUNNER, fingerprint="abc", remote_id="session_1")
    )


def test_a_rate_limit_is_worth_trying_again() -> None:
    sessions = FakeSessions(raises=RuntimeError("429 rate limit exceeded"))
    with pytest.raises(AgentTemporarilyUnavailableError):
        agent(sessions).dispatch(TASK)


def test_a_rejected_request_is_not() -> None:
    sessions = FakeSessions(raises=RuntimeError("400 invalid environment"))
    with pytest.raises(AgentUnavailableError) as raised:
        agent(sessions).dispatch(TASK)
    assert not isinstance(raised.value, AgentTemporarilyUnavailableError)


def test_a_session_without_its_own_token_is_refused() -> None:
    with pytest.raises(ValueError, match="token of its own"):
        ManagedAgent(
            client=FakeClient(FakeSessions()),
            repository_token="",
            settings=SETTINGS,
        )


def test_a_session_still_working_is_running_not_stopped() -> None:
    """A session that is neither idle nor over is still working, even
    if it has written something.
    """
    sessions = FakeSessions(
        events=[message("This commit looks like the fix. I will read it.")],
        status="running",
    )
    run = agent(sessions).collect(
        AgentHandle(runner=RUNNER, fingerprint="abc", remote_id="session_1")
    )
    assert run.outcome == "running"


def test_a_session_that_ended_without_answering_stopped_short() -> None:
    sessions = FakeSessions(events=[], status="terminated")
    run = agent(sessions).collect(
        AgentHandle(runner=RUNNER, fingerprint="abc", remote_id="session_1")
    )
    assert run.outcome == "stopped_short"


def test_a_session_with_no_money_limit_is_sent_no_budget() -> None:
    sessions = FakeSessions()
    agent(sessions).dispatch(
        AgentTask(
            instructions="Read it.",
            inputs="",
            repository="orchard/pear-tree",
            commit="a" * 40,
            head="b" * 40,
            artifact_schema={},
            budget=Budget(usd=None, turns=60),
        )
    )
    (created,) = sessions.created
    assert "budget" not in created


def test_a_session_with_a_money_limit_is_sent_it_in_cents() -> None:
    sessions = FakeSessions()
    agent(sessions).dispatch(
        AgentTask(
            instructions="Read it.",
            inputs="",
            repository="orchard/pear-tree",
            commit="a" * 40,
            head="b" * 40,
            artifact_schema={},
            budget=Budget(usd=2.5, turns=60),
        )
    )
    (created,) = sessions.created
    assert created["budget"]["max_list_cost"]["amount"] == "250"


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"write_up": {"type": "string"}},
    "required": ["write_up"],
}


def event(**fields: Any) -> Thing:
    """A session event with the given fields."""
    return Thing(
        type=fields["type"], model_dump=lambda mode="json": dict(fields)
    )


def submitted(answer: Any, use_id: str = "sevt_1") -> Thing:
    """The event in which the agent calls ``submit`` with an answer."""
    return event(
        type="agent.custom_tool_use",
        id=use_id,
        name="submit",
        input={"answer": answer},
    )


def refused(use_id: str) -> Thing:
    """The event that tells the agent its submitted answer did not
    match.
    """
    return event(
        type="user.custom_tool_result",
        custom_tool_use_id=use_id,
        content=[{"type": "text", "text": "no"}],
        is_error=True,
    )


def shaped(attempts: int = 3) -> AgentHandle:
    """A handle for a task whose answer must match ``SCHEMA``, with the
    given number of attempts.
    """
    return AgentHandle(
        runner=RUNNER,
        fingerprint="f",
        remote_id="session_1",
        artifact_schema=SCHEMA,
        attempts=attempts,
    )


def sent(sessions: FakeSessions) -> list[dict[str, Any]]:
    """Every event the adapter sent to the session."""
    return [one for _, events in sessions.events.sent for one in events]


def test_the_answers_shape_follows_the_head_commit() -> None:
    sessions = FakeSessions()
    agent(sessions).dispatch(replace(TASK, artifact_schema=SCHEMA))
    events = sessions.created[0]["initial_events"]
    assert len(events) == 3
    assert "submit" in events[2]["content"][0]["text"]
    assert '"write_up"' in events[2]["content"][0]["text"]


def test_a_task_with_no_shape_is_asked_for_none() -> None:
    sessions = FakeSessions()
    agent(sessions).dispatch(TASK)
    assert len(sessions.created[0]["initial_events"]) == 2


def test_the_handle_carries_the_shape_and_the_attempts() -> None:
    handle = agent(FakeSessions()).dispatch(
        replace(TASK, artifact_schema=SCHEMA, attempts=3)
    )
    assert (handle.artifact_schema, handle.attempts) == (SCHEMA, 3)


def test_an_answer_in_shape_is_accepted_and_is_the_artifact() -> None:
    sessions = FakeSessions(
        events=[
            submitted({"write_up": "Nothing reachable."}),
            idle("requires_action"),
        ]
    )
    run = agent(sessions).collect(shaped())
    assert run.outcome == "completed"
    assert run.artifact == {"write_up": "Nothing reachable."}
    (reply,) = sent(sessions)
    assert reply["custom_tool_use_id"] == "sevt_1"
    assert reply["is_error"] is False


def test_an_answer_out_of_shape_is_told_why_and_asked_again() -> None:
    sessions = FakeSessions(
        events=[submitted({"summary": "x"}), idle("requires_action")]
    )
    run = agent(sessions).collect(shaped())
    assert run.outcome == "running"
    (reply,) = sent(sessions)
    assert reply["is_error"] is True
    assert "write_up" in reply["content"][0]["text"]


def test_the_last_attempt_out_of_shape_ends_the_run_malformed() -> None:
    sessions = FakeSessions(
        events=[
            submitted({"write_up": "First go.", "extra": 1}, "sevt_1"),
            refused("sevt_1"),
            submitted({"summary": "second"}, "sevt_2"),
            refused("sevt_2"),
            submitted({"summary": "third"}, "sevt_3"),
            idle("requires_action"),
        ]
    )
    run = agent(sessions).collect(shaped())
    assert run.outcome == "malformed"
    assert run.artifact == {"write_up": "First go."}
    assert sessions.archived == ["session_1"]


def test_a_session_that_ended_in_prose_is_asked_to_submit() -> None:
    sessions = FakeSessions(
        events=[message("The change is safe."), idle("end_turn")]
    )
    run = agent(sessions).collect(shaped())
    assert run.outcome == "running"
    (ask,) = sent(sessions)
    assert ask["type"] == "user.message"


def test_prose_with_no_attempt_left_keeps_the_first_answer() -> None:
    sessions = FakeSessions(
        events=[message("The change is safe."), idle("end_turn")]
    )
    run = agent(sessions).collect(shaped(attempts=1))
    assert run.outcome == "malformed"
    assert run.artifact == {"write_up": "The change is safe."}
    assert sent(sessions) == []


def test_an_ask_already_in_the_log_counts_as_an_attempt() -> None:
    """Attempts are counted from the session's events, so collecting
    again does not ask again.
    """
    sessions = FakeSessions(
        events=[
            message("First answer."),
            event(
                type="user.message",
                content=[{"type": "text", "text": ASK_FOR_SUBMIT}],
            ),
            message("Second answer, still prose."),
            idle("end_turn"),
        ]
    )
    run = agent(sessions).collect(shaped(attempts=2))
    assert run.outcome == "malformed"
    assert run.artifact == {"write_up": "First answer."}


def test_a_session_that_ended_unsubmitted_is_never_completed() -> None:
    sessions = FakeSessions(
        events=[message("The change is safe.")], status="terminated"
    )
    run = agent(sessions).collect(shaped())
    assert run.outcome == "malformed"


class Turning(FakeSessions):
    """Sessions that report "running" a given number of times and then
    "idle".
    """

    def __init__(self, working: int) -> None:
        super().__init__(status="running")
        self.left = working
        self.asked = 0

    def retrieve(self, session_id: str) -> Thing:
        self.asked += 1
        if self.left > 0:
            self.left -= 1
            return Thing(status="running")
        return Thing(status="idle")


def waiting(sessions: FakeSessions, clock: list[float]) -> ManagedAgent:
    """The adapter with a clock a test controls: sleeping moves the
    clock forward and records how long was slept.
    """

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    return ManagedAgent(
        client=FakeClient(sessions),
        repository_token="a-read-only-token",
        settings=SETTINGS,
        sleep=sleep,
        now=lambda: clock[0],
    )


def test_the_wait_returns_when_the_session_stops_working() -> None:
    sessions = Turning(working=3)
    clock = [0.0]
    ready = waiting(sessions, clock).wait(
        AgentHandle(runner=RUNNER, fingerprint="f", remote_id="session_1"),
        patience=600.0,
    )
    assert ready
    assert sessions.asked == 4


def test_the_wait_gives_up_when_patience_runs_out() -> None:
    sessions = FakeSessions(status="running")
    clock = [0.0]
    ready = waiting(sessions, clock).wait(
        AgentHandle(runner=RUNNER, fingerprint="f", remote_id="session_1"),
        patience=45.0,
    )
    assert not ready
    assert clock[0] == pytest.approx(45.0)


def test_a_run_already_in_hand_is_not_waited_for() -> None:
    """A handle that carries its run needs no call to the platform."""
    sessions = FakeSessions(status="running")
    clock = [0.0]
    handle = AgentHandle(
        runner=RUNNER,
        fingerprint="f",
        run=AgentRun(outcome="completed", runner=RUNNER),
    )
    assert waiting(sessions, clock).wait(handle, patience=600.0)
    assert clock[0] == 0.0


def test_a_dispatched_run_carries_the_patience_it_deserves() -> None:
    sessions = FakeSessions()
    handle = agent(sessions).dispatch(TASK)
    assert handle.patience == PATIENCE
