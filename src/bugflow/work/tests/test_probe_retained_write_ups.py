"""Tests of ``ProbeRetainedWriteUpsUseCase``: a runner is asked which
finished runs it still holds, and their write-ups are stored if the use
case is set up to store them."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.work.domain.errors import (
    AgentUnavailableError,
    WriteUpNotKeptError,
)
from bugflow.work.domain.facts import AGENT_DISPATCHED
from bugflow.work.domain.models.agent import AgentHandle, AgentRun, AgentTask
from bugflow.work.domain.models.journal import DispatchedWork
from bugflow.work.domain.services.dispatch_record import DispatchRecordService
from bugflow.work.dtos.probe_retained_write_ups import (
    ProbeRetainedWriteUpsRequest,
    ProbeRetainedWriteUpsResponse,
)
from bugflow.work.tests.journal import QueryableJournal
from bugflow.work.usecases.probe_retained_write_ups import (
    ProbeRetainedWriteUpsUseCase,
)

RUNNER = "hosted"
WORKFLOW = "pr/github/orchard/pear-tree/6"


class FakeRecord:
    """A fixed list of recorded dispatches."""

    def __init__(self, *work: DispatchedWork) -> None:
        self.work = list(work)

    def dispatched_work(self) -> list[DispatchedWork]:
        return list(self.work)


class FakeRunner:
    """A runner that still holds some runs and refuses to return others.

    ``held`` maps the runner's name for a piece of work to its write-up.
    ``refusing`` maps one to the message the runner refuses with.
    Dispatching or stopping fails the test: the use case must do
    neither.
    """

    def __init__(
        self,
        held: dict[str, str] | None = None,
        refusing: dict[str, str] | None = None,
    ) -> None:
        self.held = held or {}
        self.refusing = refusing or {}
        self.collected: list[str] = []

    @property
    def runner(self) -> str:
        return RUNNER

    @property
    def fingerprint(self) -> str:
        return "fake"

    def dispatch(self, task: AgentTask) -> AgentHandle:
        raise AssertionError("the use case must dispatch nothing")

    @property
    def notifies(self) -> bool:
        return False

    def wait(self, handle: AgentHandle, patience: float) -> bool:
        return True

    def collect(self, handle: AgentHandle) -> AgentRun:
        self.collected.append(handle.remote_id)
        if handle.remote_id in self.refusing:
            raise AgentUnavailableError(self.refusing[handle.remote_id])
        write_up = self.held.get(handle.remote_id, "")
        return AgentRun(
            outcome="completed" if write_up else "stopped_short",
            artifact={"write_up": write_up} if write_up else {},
            runner=RUNNER,
            detail="" if write_up else "budget reached",
        )

    def stop(self, handle: AgentHandle) -> None:
        raise AssertionError("the use case must stop nothing")


class FakeKeeper:
    """Stores write-ups in a dictionary, keyed by workflow run and
    agent. It keeps the first text stored under a key, and refuses
    everything if ``refuses`` is set."""

    def __init__(self, refuses: str = "") -> None:
        self.refuses = refuses
        self.stored: dict[str, str] = {}

    def keep(self, correlation: Correlation, agent_id: str, text: str) -> str:
        if self.refuses:
            raise WriteUpNotKeptError(self.refuses)
        key = f"{correlation.workflow_id}/{correlation.run_id}/{agent_id}"
        self.stored.setdefault(key, text)
        return key


class TickingClock:
    """A clock that is a minute later each time it is read."""

    def __init__(self) -> None:
        self._now = datetime(2030, 4, 1, tzinfo=UTC)

    def now(self) -> datetime:
        self._now += timedelta(minutes=1)
        return self._now


def work(
    remote_id: str,
    day: int = 17,
    runner: str = RUNNER,
    run_id: str = "run-1",
) -> DispatchedWork:
    return DispatchedWork(
        correlation=Correlation(workflow_id=WORKFLOW, run_id=run_id),
        occurred_at=datetime(2030, 3, day, tzinfo=UTC),
        forge="github",
        repo="orchard/pear-tree",
        pr_number=6,
        commit_sha="a" * 40,
        corpus_version=None,
        agent_id="security",
        handle=AgentHandle(
            runner=runner, fingerprint="f1", remote_id=remote_id
        ),
    )


def entry(remote_id: str, step: str = "dispatched") -> JournalEntry:
    """A journal entry about a dispatch, as it is recorded."""
    return JournalEntry(
        event_id=uuid4(),
        occurred_at=datetime(2030, 3, 17, tzinfo=UTC),
        event_type=AGENT_DISPATCHED,
        forge="github",
        repo="orchard/pear-tree",
        pr_number=6,
        commit_sha="a" * 40,
        corpus_version=None,
        workflow_id=WORKFLOW,
        run_id="run-1",
        agent_id="security",
        payload={
            "agent_id": "security",
            "step": step,
            "runner": RUNNER,
            "fingerprint": "f1",
            "remote_id": remote_id,
            "budget": {"usd": 5.0},
        },
    )


def probe(
    record: DispatchRecordService, runner: FakeRunner, limit: int = 0
) -> ProbeRetainedWriteUpsResponse:
    use_case = ProbeRetainedWriteUpsUseCase(record, runner)
    return use_case.execute(ProbeRetainedWriteUpsRequest(limit=limit))


def test_a_run_the_runner_still_holds_is_reported_with_its_length() -> None:
    runner = FakeRunner(held={"s-1": "  The change does what it says. "})

    response = probe(FakeRecord(work("s-1")), runner)

    assert response.runner == RUNNER
    assert (response.read, response.named) == (1, 1)
    assert (response.returned, response.recovered) == (1, 1)
    assert response.probes[0].outcome == "write_up"
    assert response.probes[0].characters == len(
        "The change does what it says."
    )


def test_a_dispatch_with_no_remote_id_is_not_asked_about() -> None:
    runner = FakeRunner()

    response = probe(FakeRecord(work("")), runner)

    assert response.probes[0].outcome == "no_remote_id"
    assert (response.unnamed, response.named) == (1, 0)
    assert (response.returned, response.recovered) == (0, 0)
    assert runner.collected == []


def test_a_run_the_runner_refuses_to_return_is_unreachable() -> None:
    runner = FakeRunner(refusing={"s-2": "404: session not found"})

    response = probe(FakeRecord(work("s-2")), runner)

    assert response.unreachable == 1
    assert (response.returned, response.recovered) == (0, 0)
    assert response.refusals == (("404: session not found", 1),)
    assert response.oldest is None


def test_a_run_returned_with_only_white_space_has_no_write_up() -> None:
    runner = FakeRunner(held={"s-3": "   "})

    response = probe(FakeRecord(work("s-3")), runner)

    assert response.probes[0].outcome == "no_write_up"
    assert response.probes[0].characters == 0
    assert (response.returned, response.recovered) == (1, 0)
    assert response.empty == 1


def test_a_dispatch_to_another_runner_is_counted_and_not_asked_about() -> None:
    runner = FakeRunner(held={"s-4": "a write-up"})

    response = probe(FakeRecord(work("s-4", runner="local")), runner)

    assert response.elsewhere == 1
    assert response.returned == 0
    assert "local" in response.probes[0].detail
    assert runner.collected == []


def test_oldest_and_newest_cover_only_the_runs_that_had_a_write_up() -> None:
    runner = FakeRunner(
        held={"s-5": "old", "s-7": "new"}, refusing={"s-9": "410: expired"}
    )
    record = FakeRecord(
        work("s-5", day=17), work("s-7", day=20), work("s-9", day=22)
    )

    response = probe(record, runner)

    assert response.recovered == 2
    assert response.oldest == datetime(2030, 3, 17, tzinfo=UTC)
    assert response.newest == datetime(2030, 3, 20, tzinfo=UTC)


def test_a_limit_asks_about_the_oldest_dispatches_only() -> None:
    runner = FakeRunner(held={"s-1": "a", "s-2": "b"})

    response = probe(FakeRecord(work("s-1"), work("s-2", day=18)), runner, 1)

    assert response.read == 1
    assert runner.collected == ["s-1"]


def test_only_an_entry_that_started_a_run_is_asked_about() -> None:
    """An entry whose step is "unavailable" has the same type as a
    dispatch, and started no run."""
    journal = QueryableJournal()
    journal.append([entry("", step="unavailable"), entry("s-1")])

    response = probe(journal, FakeRunner(held={"s-1": "a write-up"}))

    assert response.read == 1
    assert response.probes[0].agent_id == "security"


def test_with_no_keeper_nothing_is_written_to_the_journal() -> None:
    journal = QueryableJournal()
    journal.append([entry("s-1")])
    before = list(journal.entries)

    probe(journal, FakeRunner(held={"s-1": "a write-up"}))

    assert journal.entries == before


def test_a_write_up_is_stored_and_a_fact_gives_its_key() -> None:
    journal = QueryableJournal()
    journal.append([entry("s-1")])
    keeper = FakeKeeper()
    use_case = ProbeRetainedWriteUpsUseCase(
        journal,
        FakeRunner(held={"s-1": "a write-up"}),
        keeper,
        journal,
        TickingClock(),
    )

    response = use_case.execute(ProbeRetainedWriteUpsRequest())

    key = f"{WORKFLOW}/run-1/security"
    assert keeper.stored == {key: "a write-up"}
    assert response.kept == 1
    assert response.probes[0].write_up_id == key
    (fact,) = [
        e for e in journal.entries if e.payload.get("step") == "recovered"
    ]
    assert fact.event_type == AGENT_DISPATCHED
    assert fact.payload["write_up_id"] == key
    assert fact.payload["remote_id"] == "s-1"
    assert fact.payload["outcome"] == "completed"
    assert fact.payload["dispatched_at"] == "2030-03-17T00:00:00+00:00"
    assert (fact.workflow_id, fact.run_id) == (WORKFLOW, "run-1")


def test_storing_the_same_run_twice_writes_one_fact() -> None:
    journal = QueryableJournal()
    journal.append([entry("s-1")])
    keeper = FakeKeeper()
    use_case = ProbeRetainedWriteUpsUseCase(
        journal,
        FakeRunner(held={"s-1": "a write-up"}),
        keeper,
        journal,
        TickingClock(),
    )

    use_case.execute(ProbeRetainedWriteUpsRequest())
    second = use_case.execute(ProbeRetainedWriteUpsRequest())

    assert second.read == 1
    assert len(keeper.stored) == 1
    assert (
        len([e for e in journal.entries if e.payload["step"] == "recovered"])
        == 1
    )


def test_a_write_up_that_cannot_be_stored_writes_no_fact() -> None:
    journal = QueryableJournal()
    journal.append([entry("s-1")])
    before = list(journal.entries)
    use_case = ProbeRetainedWriteUpsUseCase(
        journal,
        FakeRunner(held={"s-1": "a write-up"}),
        FakeKeeper(refuses="the store is read-only"),
        journal,
        TickingClock(),
    )

    response = use_case.execute(ProbeRetainedWriteUpsRequest())

    assert response.probes[0].outcome == "not_kept"
    assert response.probes[0].detail == "the store is read-only"
    assert (response.recovered, response.kept, response.refused) == (1, 0, 1)
    assert journal.entries == before


def test_a_keeper_without_a_journal_and_a_clock_is_refused() -> None:
    with pytest.raises(ValueError, match="all three or none"):
        ProbeRetainedWriteUpsUseCase(
            FakeRecord(), FakeRunner(), keeper=FakeKeeper()
        )
