"""Tests of the four steps of a checkout agent's review: dispatch, wait,
collect and grade."""

from pathlib import Path

import pytest

from bugflow.review.domain.errors import (
    AgentUnavailableError,
    GraderUnavailableError,
    WorktreeUnavailableError,
)
from bugflow.review.domain.facts import (
    AGENT_DISPATCHED,
    LLM_CALLED,
    REVIEW_GRADED,
)
from bugflow.review.domain.models.delegation import Handle, Run, Task
from bugflow.review.domain.models.grading import Grading, Writeup
from bugflow.review.domain.models.write_up import WriteUp
from bugflow.review.dtos.collect_review import CollectReviewRequest
from bugflow.review.dtos.dispatch_review import (
    DispatchReviewRequest,
    DispatchReviewResponse,
)
from bugflow.review.dtos.grade_review import (
    GradeReviewRequest,
    GradeReviewResponse,
)
from bugflow.review.dtos.wait_review import WaitReviewRequest
from bugflow.review.infrastructure.in_memory_write_up_archive import (
    InMemoryWriteUpArchive,
)
from bugflow.review.tests.doubles import NOW, FixedClock
from bugflow.review.tests.journal import QueryableJournal
from bugflow.review.usecases.collect_review import CollectReviewUseCase
from bugflow.review.usecases.dispatch_review import (
    ATTEMPTS,
    WRITE_UP_SCHEMA,
    DispatchReviewUseCase,
)
from bugflow.review.usecases.grade_review import GradeReviewUseCase
from bugflow.review.usecases.wait_review import WaitReviewUseCase
from bugflow.shared.domain.models.call_record import CallRecord
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.budget import Budget
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="orchard", repo="pear-tree", number=5)
RUN_1 = Correlation(workflow_id="pr/5", run_id="run-1")
RUN_2 = Correlation(workflow_id="pr/5", run_id="run-2")
HEAD, BASE = "a" * 40, "b" * 40
WRITE_UP = "I read the diff.\n\n## For the author\n\nRename `x`."


class FakeRunner:
    """A runner that records the tasks it is given. ``run`` is what
    ``collect`` returns. ``down`` makes every call raise."""

    fingerprint = "runner-v1"
    runner = "hosted"
    notifies = False

    def __init__(self, run: Run | None = None, down: bool = False) -> None:
        self.run = run or Run(outcome="completed")
        self.down = down
        self.tasks: list[Task] = []
        self.waited: list[float] = []

    def _check(self) -> None:
        if self.down:
            raise AgentUnavailableError("the runner is down")

    def dispatch(self, task: Task) -> Handle:
        self._check()
        self.tasks.append(task)
        return Handle(
            runner=self.runner,
            fingerprint=self.fingerprint,
            remote_id="s-1",
            budget=task.budget,
            patience=600.0,
        )

    def wait(self, handle: Handle, patience: float) -> bool:
        self._check()
        self.waited.append(patience)
        return patience >= 60

    def collect(self, handle: Handle) -> Run:
        self._check()
        return self.run

    def stop(self, handle: Handle) -> None:
        self._check()


class FakeWorktrees:
    """Prepares no directory. It records what it was asked for and
    returns two removed paths, or raises if ``broken``."""

    def __init__(self, broken: bool = False) -> None:
        self.broken = broken
        self.prepared: list[tuple[str, Path, str]] = []

    def prepare(
        self,
        ref: PullRequestRef,
        head_sha: str,
        into: Path,
        base_sha: str = "",
    ) -> tuple[str, ...]:
        if self.broken:
            raise WorktreeUnavailableError("no access")
        self.prepared.append((head_sha, into, base_sha))
        return ("AGENTS.md", ".claude")


def call(call_id: str) -> CallRecord:
    return CallRecord(
        call_id=call_id,
        purpose="grade",
        requested_model="small",
        started_at=NOW,
        ended_at=NOW,
        client_duration_ms=1.0,
    )


class FakeGrader:
    """Returns the grading it is given, or raises if ``down``."""

    def __init__(self, grading: Grading, down: bool = False) -> None:
        self.grading = grading
        self.down = down
        self.read: list[Writeup] = []

    def grade(self, writeup: Writeup) -> Grading:
        self.read.append(writeup)
        if self.down:
            raise GraderUnavailableError("busy", calls=(call("c-failed"),))
        return self.grading


def dispatch(
    journal: QueryableJournal,
    runner: FakeRunner,
    worktrees: FakeWorktrees | None = None,
    correlation: Correlation = RUN_1,
    **changed: object,
) -> DispatchReviewResponse:
    return DispatchReviewUseCase(
        worktrees, runner, journal, FixedClock()
    ).execute(
        DispatchReviewRequest(
            **{
                "ref": REF,
                "head_sha": HEAD,
                "base_sha": BASE,
                "agent_id": "safety",
                "corpus_version": "safety-2",
                "instructions": "Look for unsafe code.",
                "worktree": Path("/work/pr-5"),
                "budget": Budget(usd=2.0, turns=30.0),
                "correlation": correlation,
                **changed,
            }  # type: ignore[arg-type]
        )
    )


def grade(
    journal: QueryableJournal,
    grader: FakeGrader,
    run: Run | None = None,
    correlation: Correlation = RUN_1,
) -> GradeReviewResponse:
    return GradeReviewUseCase(grader, journal, FixedClock()).execute(
        GradeReviewRequest(
            ref=REF,
            head_sha=HEAD,
            agent_id="safety",
            corpus_version="safety-2",
            correlation=correlation,
            run=run
            or Run(outcome="completed", artifact={"write_up": WRITE_UP}),
        )
    )


def steps(journal: QueryableJournal) -> list[str]:
    return [
        str(e.payload["step"])
        for e in journal.entries
        if e.event_type == AGENT_DISPATCHED
    ]


def last(journal: QueryableJournal) -> JournalEntry:
    return journal.entries[-1]


def test_a_run_is_started_and_recorded() -> None:
    journal, runner, worktrees = (
        QueryableJournal(),
        FakeRunner(),
        FakeWorktrees(),
    )

    response = dispatch(journal, runner, worktrees)

    assert response.handle is not None
    assert response.handle.remote_id == "s-1"
    assert response.withheld == ("AGENTS.md", ".claude")
    assert worktrees.prepared == [(HEAD, Path("/work/pr-5"), BASE)]
    (task,) = runner.tasks
    assert task.instructions == "Look for unsafe code."
    assert task.inputs == "/work/pr-5"
    assert (task.repository, task.commit, task.head) == (
        "orchard/pear-tree",
        BASE,
        HEAD,
    )
    assert task.artifact_schema == WRITE_UP_SCHEMA
    assert task.attempts == ATTEMPTS
    entry = last(journal)
    assert entry.payload == {
        "agent_id": "safety",
        "step": "dispatched",
        "runner": "hosted",
        "fingerprint": "runner-v1",
        "remote_id": "s-1",
        "budget": {"usd": 2.0, "turns": 30.0},
        "withheld": ["AGENTS.md", ".claude"],
    }
    assert (entry.agent_id, entry.corpus_version) == ("safety", "safety-2")
    assert entry.commit_sha == HEAD


def test_a_runner_that_fetches_for_itself_gets_no_directory() -> None:
    journal, runner = QueryableJournal(), FakeRunner()

    response = dispatch(journal, runner, None)

    assert runner.tasks[0].inputs is None
    assert response.withheld == ()


def test_a_refused_request_starts_nothing_and_is_recorded() -> None:
    journal, runner = QueryableJournal(), FakeRunner()

    response = dispatch(journal, runner, refusal="no allowance covers it")

    assert response.handle is None
    assert response.reason == "no allowance covers it"
    assert runner.tasks == []
    assert steps(journal) == ["refused"]
    assert last(journal).payload["reason"] == "no allowance covers it"


def test_a_worktree_that_cannot_be_prepared_starts_nothing() -> None:
    journal, runner = QueryableJournal(), FakeRunner()

    response = dispatch(journal, runner, FakeWorktrees(broken=True))

    assert response.handle is None
    assert response.reason == "no worktree: no access"
    assert runner.tasks == []
    assert steps(journal) == ["no-worktree"]


def test_a_runner_that_is_down_is_recorded_as_unavailable() -> None:
    journal = QueryableJournal()

    response = dispatch(journal, FakeRunner(down=True))

    assert response.handle is None
    assert response.reason == "the agent did not run: the runner is down"
    assert steps(journal) == ["unavailable"]


def test_a_verdict_already_given_on_the_commit_is_used_again() -> None:
    journal, runner = QueryableJournal(), FakeRunner()
    dispatch(journal, runner)
    grade(journal, FakeGrader(Grading(status="warn", detail="one thing")))

    response = dispatch(journal, runner, correlation=RUN_2)

    assert response.handle is None
    assert response.reused is not None
    assert (response.reused.status, response.reused.head_sha) == ("warn", HEAD)
    assert len(runner.tasks) == 1
    assert steps(journal) == ["dispatched", "reused"]
    assert last(journal).payload["reviewed_in"] == "run-1"
    assert last(journal).run_id == "run-2"


def test_no_verdict_is_used_again_after_the_runner_changed() -> None:
    journal, runner = QueryableJournal(), FakeRunner()
    dispatch(journal, runner)
    grade(journal, FakeGrader(Grading(status="pass")))
    changed = FakeRunner()
    changed.fingerprint = "runner-v2"

    response = dispatch(journal, changed, correlation=RUN_2)

    assert response.reused is None
    assert response.handle is not None


def test_a_grading_with_no_verdict_is_not_used_again() -> None:
    journal, runner = QueryableJournal(), FakeRunner()
    dispatch(journal, runner)
    grade(journal, FakeGrader(Grading(status=None)))

    response = dispatch(journal, runner, correlation=RUN_2)

    assert response.reused is None
    assert len(runner.tasks) == 2


def wait_request(handle: Handle, patience: float = 0.0) -> WaitReviewRequest:
    return WaitReviewRequest(
        ref=REF,
        head_sha=HEAD,
        agent_id="safety",
        correlation=RUN_1,
        handle=handle,
        patience=patience,
    )


HANDLE = Handle(
    runner="hosted", fingerprint="runner-v1", remote_id="s-1", patience=600.0
)


def test_waiting_takes_the_handles_time_unless_told_another() -> None:
    runner = FakeRunner()
    use_case = WaitReviewUseCase(runner)

    assert use_case.execute(wait_request(HANDLE)).ready
    assert not use_case.execute(wait_request(HANDLE, patience=5.0)).ready
    assert runner.waited == [600.0, 5.0]


def test_waiting_on_a_runner_that_is_down_is_not_ready() -> None:
    response = WaitReviewUseCase(FakeRunner(down=True)).execute(
        wait_request(HANDLE)
    )

    assert not response.ready


def collect_request() -> CollectReviewRequest:
    return CollectReviewRequest(
        ref=REF,
        head_sha=HEAD,
        agent_id="safety",
        corpus_version="safety-2",
        correlation=RUN_1,
        handle=HANDLE,
    )


def test_a_finished_run_is_recorded_and_its_write_up_stored() -> None:
    journal, archive = QueryableJournal(), InMemoryWriteUpArchive()
    run = Run(
        outcome="completed",
        artifact={"write_up": WRITE_UP},
        transcript=({"type": "message"}, {"type": "idle"}),
        cost={"usd": 0.4},
        runner="hosted",
        fingerprint="runner-v1",
    )

    response = CollectReviewUseCase(
        FakeRunner(run), journal, FixedClock(), archive
    ).execute(collect_request())

    assert response.run == run
    assert response.reason == ""
    key = "pr/5/run-1/safety"
    assert archive.get(key) == WriteUp(
        correlation=RUN_1, agent_id="safety", text=WRITE_UP
    )
    assert last(journal).payload == {
        "agent_id": "safety",
        "step": "collected",
        "outcome": "completed",
        "runner": "hosted",
        "fingerprint": "runner-v1",
        "cost": {"usd": 0.4},
        "events": 2,
        "detail": "",
        "write_up_id": key,
    }


def test_a_run_that_is_still_going_is_not_recorded() -> None:
    journal = QueryableJournal()

    response = CollectReviewUseCase(
        FakeRunner(Run(outcome="running")), journal, FixedClock()
    ).execute(collect_request())

    assert response.reason == "the run has not finished"
    assert journal.entries == []


def test_a_run_that_stopped_short_is_recorded_with_the_reason() -> None:
    journal = QueryableJournal()
    run = Run(outcome="stopped_short", detail="budget reached")

    response = CollectReviewUseCase(
        FakeRunner(run), journal, FixedClock(), InMemoryWriteUpArchive()
    ).execute(collect_request())

    assert response.reason == "the run stopped short: budget reached"
    assert last(journal).payload["outcome"] == "stopped_short"
    assert "write_up_id" not in last(journal).payload


def test_a_run_that_cannot_be_read_gives_no_run() -> None:
    journal = QueryableJournal()

    response = CollectReviewUseCase(
        FakeRunner(down=True), journal, FixedClock()
    ).execute(collect_request())

    assert response.run is None
    assert response.reason == ("the run could not be read: the runner is down")
    assert journal.entries == []


def test_a_grading_gives_a_verdict_and_a_note_and_is_recorded() -> None:
    journal = QueryableJournal()
    grader = FakeGrader(
        Grading(
            status="warn",
            detail="one thing to change",
            note_fit=True,
            calls=(call("c-1"),),
        )
    )

    response = grade(journal, grader)

    assert grader.read[0].write_up == WRITE_UP
    assert response.verdict is not None
    assert response.verdict.status == "warn"
    assert response.note is not None
    assert (response.note.note, response.note.write_up) == ("Rename `x`.", "")
    assert response.grading.calls == ()
    assert [e.event_type for e in journal.entries] == [
        LLM_CALLED,
        REVIEW_GRADED,
    ]
    assert last(journal).payload == {
        "agent_id": "safety",
        "status": "warn",
        "detail": "one thing to change",
    }
    assert journal.entries[0].payload["call_id"] == "c-1"
    assert journal.entries[0].agent_id == "safety"


def test_a_note_that_is_not_fit_is_replaced_by_the_whole_write_up() -> None:
    response = grade(
        QueryableJournal(), FakeGrader(Grading(status="pass", note_fit=False))
    )

    assert response.note is not None
    assert response.note.note == ""
    assert response.note.write_up == WRITE_UP


def test_a_write_up_that_answers_nothing_gives_no_verdict() -> None:
    journal = QueryableJournal()

    response = grade(journal, FakeGrader(Grading(status=None)))

    assert response.verdict is None and response.note is None
    assert response.reason == "the write-up answered nothing"
    assert last(journal).payload["status"] is None


def test_a_grader_that_is_down_raises_after_its_calls_are_recorded() -> None:
    journal = QueryableJournal()

    with pytest.raises(GraderUnavailableError):
        grade(journal, FakeGrader(Grading(), down=True))

    (entry,) = journal.entries
    assert entry.event_type == LLM_CALLED
    assert entry.payload["call_id"] == "c-failed"
