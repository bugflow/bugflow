"""Tests of the four steps of a stocktake's review of its range:
dispatch, wait, collect and grade."""

from datetime import UTC, datetime

import pytest

from bugflow.review.domain.errors import (
    AgentUnavailableError,
    GraderUnavailableError,
)
from bugflow.review.domain.models.delegation import (
    Handle,
    Run,
    Task,
    TaskOutcome,
)
from bugflow.review.domain.models.grading import (
    Grading,
    Writeup,
)
from bugflow.review.dtos.review_range import (
    CollectRangeReviewRequest,
    DispatchRangeReviewRequest,
    GradeRangeReviewRequest,
)
from bugflow.review.tests.journal import QueryableJournal
from bugflow.review.usecases.review_range import (
    CollectRangeReviewUseCase,
    DispatchRangeReviewUseCase,
    GradeRangeReviewUseCase,
)
from bugflow.shared.domain.models.call_record import CallRecord
from bugflow.shared.domain.values.budget import Budget
from bugflow.shared.domain.values.correlation import Correlation

AT = datetime(2030, 9, 27, 13, 30, tzinfo=UTC)
RUN = Correlation(workflow_id="stocktake/weekly", run_id="s-1")
BASE, HEAD = "b" * 40, "a" * 40


class Clock:
    def now(self) -> datetime:
        return AT


class FakeAgent:
    def __init__(
        self,
        fail: str = "",
        outcome: TaskOutcome = "completed",
        findings: list[dict[str, str]] | None = None,
    ) -> None:
        self.waited: list[float] = []
        self._fail = fail
        self._outcome = outcome
        self._findings = findings
        self.tasks: list[Task] = []

    @property
    def runner(self) -> str:
        return "hosted"

    @property
    def fingerprint(self) -> str:
        return "runner-1"

    def dispatch(self, task: Task) -> Handle:
        if self._fail:
            raise AgentUnavailableError(self._fail)
        self.tasks.append(task)
        return Handle(
            runner="hosted", fingerprint="runner-1", remote_id="ses-1"
        )

    @property
    def notifies(self) -> bool:
        return False

    def wait(self, handle: Handle, patience: float) -> bool:
        self.waited.append(patience)
        return True

    def collect(self, handle: Handle) -> Run:
        artifact: dict[str, object] = {
            "write_up": "The token is read from the environment."
        }
        if self._findings is not None:
            artifact["findings"] = self._findings
        return Run(
            outcome=self._outcome,
            artifact=artifact,
            cost={"usd": 0.31},
            runner="hosted",
            fingerprint="runner-1",
        )

    def stop(self, handle: Handle) -> None:
        raise AssertionError("nothing here stops a run")


def dispatch(
    agent: FakeAgent, journal: QueryableJournal, base: str | None = BASE
) -> object:
    return DispatchRangeReviewUseCase(agent, journal, Clock()).execute(
        DispatchRangeReviewRequest(
            forge="github",
            repo="orchard/pear-tree",
            layer="weekly",
            agent_id="safety",
            instructions="Read what merged this week.",
            base_sha=base,
            head_sha=HEAD,
            budget=Budget(usd=5.0, turns=60),
            correlation=RUN,
        )
    )


def test_the_agent_is_given_the_week_to_read() -> None:
    agent, journal = FakeAgent(), QueryableJournal()
    response = dispatch(agent, journal)
    (task,) = agent.tasks
    assert (task.commit, task.head) == (BASE, HEAD)
    assert response.handle is not None  # type: ignore[attr-defined]
    (entry,) = journal.entries
    assert entry.event_type == "stocktake.dispatched"
    assert entry.pr_number is None
    assert entry.payload["layer"] == "weekly"


def test_a_first_stocktake_has_the_tree_rather_than_a_diff() -> None:
    agent, journal = FakeAgent(), QueryableJournal()
    dispatch(agent, journal, base=None)
    (task,) = agent.tasks
    assert (task.commit, task.head) == (HEAD, HEAD)


def test_a_review_that_could_not_be_dispatched_is_journalled() -> None:
    agent, journal = FakeAgent(fail="no api key"), QueryableJournal()
    response = dispatch(agent, journal)
    assert response.handle is None  # type: ignore[attr-defined]
    (entry,) = journal.entries
    assert entry.payload["step"] == "unavailable"
    assert "no api key" in entry.payload["reason"]


def test_what_the_week_s_review_wrote_is_recorded_with_its_cost() -> None:
    journal = QueryableJournal()
    collected = CollectRangeReviewUseCase(
        FakeAgent(), journal, Clock()
    ).execute(
        CollectRangeReviewRequest(
            forge="github",
            repo="orchard/pear-tree",
            layer="weekly",
            agent_id="safety",
            head_sha=HEAD,
            handle=Handle(
                runner="hosted",
                fingerprint="runner-1",
                remote_id="ses-1",
            ),
            correlation=RUN,
        )
    )
    assert collected.run is not None
    (entry,) = journal.entries
    assert entry.event_type == "stocktake.reviewed"
    assert entry.payload["cost"] == {"usd": 0.31}
    assert "token" in entry.payload["write_up"]


class FakeGrader:
    def __init__(self, grading: Grading | Exception) -> None:
        self._grading = grading
        self.graded: list[Writeup] = []

    def grade(self, writeup: Writeup) -> Grading:
        self.graded.append(writeup)
        if isinstance(self._grading, Exception):
            raise self._grading
        return self._grading


def grading_call(call_id: str = "call-1") -> CallRecord:
    return CallRecord(
        call_id=call_id,
        purpose="grade",
        requested_model="grader",
        cost_nanodollars=1_200_000,
        started_at=AT,
        ended_at=AT,
        client_duration_ms=900.0,
    )


def grade(grading: Grading | Exception, journal: QueryableJournal) -> object:
    return GradeRangeReviewUseCase(
        FakeGrader(grading), journal, Clock()
    ).execute(
        GradeRangeReviewRequest(
            forge="github",
            repo="orchard/pear-tree",
            layer="weekly",
            agent_id="safety",
            head_sha=HEAD,
            run=Run(
                outcome="completed",
                artifact={"write_up": "Note to the reader.\n\nThe rest."},
                cost={"usd": 0.31},
            ),
            correlation=RUN,
        )
    )


def test_a_graded_week_records_the_verdict_it_supports() -> None:
    journal = QueryableJournal()
    response = grade(
        Grading(status="warn", detail="two things to look at", note_fit=True),
        journal,
    )
    assert response.status == "warn"  # type: ignore[attr-defined]
    (entry,) = journal.entries
    assert entry.event_type == "stocktake.graded"
    assert entry.pr_number is None
    assert entry.payload["status"] == "warn"


def test_each_call_a_graded_week_made_is_journalled_with_its_cost() -> None:
    journal = QueryableJournal()
    grade(Grading(status="pass", calls=(grading_call(),)), journal)
    called, graded = journal.entries
    assert (called.event_type, graded.event_type) == (
        "llm.called",
        "stocktake.graded",
    )
    assert called.payload["cost_nanodollars"] == 1_200_000
    assert (called.repo, called.pr_number) == ("orchard/pear-tree", None)


def test_a_call_the_grader_would_not_answer_is_still_journalled() -> None:
    journal = QueryableJournal()
    with pytest.raises(GraderUnavailableError):
        grade(
            GraderUnavailableError("503", calls=(grading_call("refused"),)),
            journal,
        )
    (called,) = journal.entries
    assert called.event_type == "llm.called"
    assert called.payload["call_id"] == "refused"


def test_a_week_that_answered_nothing_supports_no_verdict() -> None:
    journal = QueryableJournal()
    response = grade(Grading(status=None, detail="answered nothing"), journal)
    assert response.status is None  # type: ignore[attr-defined]
    (entry,) = journal.entries
    assert entry.payload["status"] is None


def test_a_note_grading_would_not_show_is_kept_whole() -> None:
    journal = QueryableJournal()
    response = grade(Grading(status="pass", note_fit=False), journal)
    assert response.note == ""  # type: ignore[attr-defined]
    assert "The rest." in response.write_up  # type: ignore[attr-defined]


def collect(agent: FakeAgent, journal: QueryableJournal) -> object:
    return CollectRangeReviewUseCase(agent, journal, Clock()).execute(
        CollectRangeReviewRequest(
            forge="github",
            repo="orchard/pear-tree",
            layer="weekly",
            agent_id="safety",
            head_sha=HEAD,
            handle=Handle(
                runner="hosted",
                fingerprint="runner-1",
                remote_id="ses-1",
            ),
            correlation=RUN,
        )
    )


def test_a_run_still_going_is_not_recorded_as_what_it_did() -> None:
    journal = QueryableJournal()
    response = collect(FakeAgent(outcome="running"), journal)
    assert journal.entries == []
    assert "not finished" in response.reason  # type: ignore[attr-defined]


def test_a_run_that_is_over_is_recorded_whatever_it_did() -> None:
    journal = QueryableJournal()
    collect(FakeAgent(outcome="stopped_short"), journal)
    (entry,) = journal.entries
    assert entry.payload["outcome"] == "stopped_short"


def test_a_run_that_answered_out_of_shape_is_ready_for_grading() -> None:
    journal = QueryableJournal()
    response = collect(FakeAgent(outcome="malformed"), journal)
    (entry,) = journal.entries
    assert entry.payload["outcome"] == "malformed"
    assert response.reason == ""  # type: ignore[attr-defined]


def test_a_weeks_review_asks_for_its_findings_as_data() -> None:
    agent = FakeAgent()
    dispatch(agent, QueryableJournal())
    (task,) = agent.tasks
    assert task.artifact_schema is not None
    assert task.artifact_schema["required"] == ["write_up", "findings"]
    assert task.attempts == 3


LEAK = {
    "where": "src/app/log.py:41",
    "quote": "log.info(request.headers)",
    "claim": "The bearer token is written to the log.",
    "kind": "credential leak",
}
INJECTION = {
    "where": "src/app/db.py:12",
    "quote": 'f"SELECT * FROM t WHERE id={id}"',
    "claim": "The id reaches the query unescaped.",
}


def found(journal: QueryableJournal) -> list[object]:
    return [e for e in journal.entries if e.event_type == "stocktake.found"]


def test_each_finding_of_a_weeks_review_is_a_fact_of_its_own() -> None:
    journal = QueryableJournal()
    collect(FakeAgent(findings=[LEAK, INJECTION]), journal)
    facts = found(journal)
    assert [f.payload["where"] for f in facts] == [  # type: ignore[attr-defined]
        "src/app/log.py:41",
        "src/app/db.py:12",
    ]
    leak = facts[0]
    assert leak.payload["claim"] == LEAK["claim"]  # type: ignore[attr-defined]
    assert leak.payload["kind"] == "credential leak"  # type: ignore[attr-defined]
    assert leak.occurred_at == AT  # type: ignore[attr-defined]
    assert (leak.commit_sha, leak.run_id) == (HEAD, RUN.run_id)  # type: ignore[attr-defined]


def test_a_week_with_nothing_found_records_no_finding() -> None:
    journal = QueryableJournal()
    collect(FakeAgent(findings=[]), journal)
    assert found(journal) == []


def test_a_run_that_answered_out_of_shape_records_no_finding() -> None:
    journal = QueryableJournal()
    collect(FakeAgent(outcome="malformed", findings=[LEAK]), journal)
    assert found(journal) == []


def test_collecting_a_run_twice_records_each_finding_once() -> None:
    journal = QueryableJournal()
    collect(FakeAgent(findings=[LEAK]), journal)
    collect(FakeAgent(findings=[LEAK]), journal)
    assert len(found(journal)) == 1


def dispatched_payload(journal: QueryableJournal) -> dict[str, object]:
    (entry,) = [
        e for e in journal.entries if e.event_type == "stocktake.dispatched"
    ]
    return dict(entry.payload)


def test_the_dispatch_names_the_runner_a_completion_is_found_by() -> None:
    agent, journal = FakeAgent(), QueryableJournal()
    dispatch(agent, journal)
    payload = dispatched_payload(journal)
    assert payload["runner"] == "hosted"
    assert payload["remote_id"] == "ses-1"


def test_a_refused_dispatch_is_recorded_and_asks_nobody() -> None:
    agent, journal = FakeAgent(), QueryableJournal()
    response = DispatchRangeReviewUseCase(agent, journal, Clock()).execute(
        DispatchRangeReviewRequest(
            forge="github",
            repo="orchard/pear-tree",
            layer="weekly",
            agent_id="safety",
            instructions="",
            base_sha=BASE,
            head_sha=HEAD,
            correlation=RUN,
            refusal="github:o/r is allowed $10.00 per day and has spent "
            "$10.00",
        )
    )
    assert agent.tasks == []
    assert response.handle is None
    (entry,) = journal.entries
    assert entry.payload["step"] == "refused"
    assert "has spent $10.00" in entry.payload["reason"]
    assert "$10.00 per day" in response.reason
