"""Tests of ``ReceiveCompletionUseCase``: a completion is passed to the
workflow run that dispatched the work, and is always recorded."""

from datetime import UTC, datetime
from uuid import uuid4

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.acknowledgement import Acknowledgement
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.work.domain.facts import AGENT_DISPATCHED, COMPLETION_RECEIVED
from bugflow.work.domain.models.completion import Completion
from bugflow.work.dtos.receive_completion import (
    ReceiveCompletionRequest,
    ReceiveCompletionResponse,
)
from bugflow.work.tests.journal import QueryableJournal
from bugflow.work.usecases.receive_completion import ReceiveCompletionUseCase

RUN = Correlation(workflow_id="pr/github/orchard/pear-tree/6", run_id="run-1")
WHEN = datetime(2030, 3, 27, 3, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return WHEN


class FakeHandler:
    """Records what it was told. ``waiting`` says whether a workflow run
    is still waiting for the completion."""

    def __init__(self, waiting: bool = True) -> None:
        self.waiting = waiting
        self.told: list[tuple[Correlation, str, str]] = []

    def handle_completion(
        self, correlation: Correlation, agent_id: str, remote_id: str
    ) -> Acknowledgement:
        self.told.append((correlation, agent_id, remote_id))
        if not self.waiting:
            return Acknowledgement.unable()
        return Acknowledgement.wilco()


def dispatched(agent_id: str, remote_id: str, runner: str) -> JournalEntry:
    """The journal entry for one dispatch."""
    return JournalEntry(
        event_id=uuid4(),
        occurred_at=datetime(2030, 3, 21, tzinfo=UTC),
        event_type=AGENT_DISPATCHED,
        forge="github",
        repo="orchard/pear-tree",
        pr_number=6,
        commit_sha="a" * 40,
        corpus_version=None,
        workflow_id=RUN.workflow_id,
        run_id=RUN.run_id,
        payload={
            "agent_id": agent_id,
            "step": "dispatched",
            "runner": runner,
            "remote_id": remote_id,
        },
    )


def receive(
    journal: QueryableJournal, handler: FakeHandler, remote_id: str
) -> ReceiveCompletionResponse:
    use_case = ReceiveCompletionUseCase(
        journal, handler, journal, FixedClock()
    )
    return use_case.execute(
        ReceiveCompletionRequest(
            completion=Completion(runner="hosted", remote_id=remote_id)
        )
    )


def recorded(journal: QueryableJournal) -> list[JournalEntry]:
    return [e for e in journal.entries if e.event_type == COMPLETION_RECEIVED]


def test_a_completion_is_passed_to_the_run_that_dispatched_the_work() -> None:
    journal = QueryableJournal()
    journal.append([dispatched("security", "session-1", "hosted")])
    handler = FakeHandler()

    response = receive(journal, handler, "session-1")

    assert response.outcome == "signalled"
    assert handler.told == [(RUN, "security", "session-1")]
    (written,) = recorded(journal)
    assert written.payload["outcome"] == "signalled"
    assert written.payload["remote_id"] == "session-1"
    assert (written.workflow_id, written.run_id) == (
        RUN.workflow_id,
        RUN.run_id,
    )
    assert written.repo == "orchard/pear-tree"
    assert written.occurred_at == WHEN


def test_a_completion_for_work_the_journal_does_not_know() -> None:
    """Nothing is told, and the completion is still recorded, with no
    workflow run."""
    journal = QueryableJournal()
    handler = FakeHandler()

    response = receive(journal, handler, "session-9")

    assert response.outcome == "unknown"
    assert handler.told == []
    (written,) = recorded(journal)
    assert written.payload["outcome"] == "unknown"
    assert (written.workflow_id, written.run_id) == ("", "")


def test_a_dispatch_to_another_runner_is_not_a_match() -> None:
    journal = QueryableJournal()
    journal.append([dispatched("security", "session-1", "local")])

    assert receive(journal, FakeHandler(), "session-1").outcome == "unknown"


def test_a_completion_that_arrives_after_the_run_has_ended() -> None:
    journal = QueryableJournal()
    journal.append([dispatched("security", "session-1", "hosted")])

    response = receive(journal, FakeHandler(waiting=False), "session-1")

    assert response.outcome == "not_waiting"
    (written,) = recorded(journal)
    assert written.payload["outcome"] == "not_waiting"


def test_a_completion_sent_twice_is_recorded_once() -> None:
    journal = QueryableJournal()
    journal.append([dispatched("security", "session-1", "hosted")])
    handler = FakeHandler()

    receive(journal, handler, "session-1")
    receive(journal, handler, "session-1")

    assert len(recorded(journal)) == 1
