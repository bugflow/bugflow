"""Reading one run for the operations pages: what it spent, fact by
fact; each allowance that covers it, beside what the allowance
measures; and every entry it recorded."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from bugflow.review.domain.errors import RunNotFoundError
from bugflow.review.domain.models.review_entry import ReviewEntry
from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.dtos.read_run_operations import ReadRunOperationsRequest
from bugflow.review.infrastructure.in_memory_spend_bindings import (
    InMemorySpendBindings,
)
from bugflow.review.infrastructure.in_memory_spend_record import (
    InMemorySpendRecord,
    RecordedCost,
)
from bugflow.review.usecases.read_run_operations import (
    ReadRunOperationsUseCase,
)
from bugflow.shared.domain.values.budget import Budget
from bugflow.shared.domain.values.correlation import Correlation

WORKFLOW, RUN = "review/o/r/7", "run-1"
AT = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
WEEK = (AT - timedelta(days=1), AT + timedelta(days=6))


def entry(event_type: str, at: datetime, agent: str | None) -> ReviewEntry:
    return ReviewEntry(
        event_id=uuid.uuid4(),
        occurred_at=at,
        event_type=event_type,
        forge="github",
        repo="o/r",
        pr_number=7,
        commit_sha=None,
        corpus_version=None,
        workflow_id=WORKFLOW,
        run_id=RUN,
        payload={},
        agent_id=agent,
    )


class Journal:
    def __init__(self, entries: list[ReviewEntry]) -> None:
        self.entries = entries

    def entries_for_run(self, correlation: Correlation) -> list[ReviewEntry]:
        return [
            one
            for one in self.entries
            if (one.workflow_id, one.run_id)
            == (correlation.workflow_id, correlation.run_id)
        ]


def weekly_or_per_run(
    binding: SpendBinding, now: datetime
) -> tuple[datetime, datetime] | None:
    if binding.per == "week":
        return WEEK
    if binding.per == "month":
        raise ValueError("nothing says where a month period begins")
    return None


def reading(
    *bindings: SpendBinding,
) -> tuple[ReadRunOperationsUseCase, InMemorySpendRecord]:
    dispatched = entry("agent.dispatched", AT, "safety")
    judged = entry("llm.called", AT + timedelta(minutes=2), None)
    spend = InMemorySpendRecord()
    spend.recorded = [
        RecordedCost(
            event_id=str(dispatched.event_id),
            workflow_id=WORKFLOW,
            run_id=RUN,
            forge="github",
            repo="o/r",
            agent_id="safety",
            kind="agent_dispatch",
            at=dispatched.occurred_at,
            usd=0.75,
        ),
        RecordedCost(
            event_id=str(judged.event_id),
            workflow_id=WORKFLOW,
            run_id=RUN,
            forge="github",
            repo="o/r",
            at=judged.occurred_at,
            usd=0.25,
        ),
    ]
    ceilings = InMemorySpendBindings()
    for one in bindings:
        ceilings.declare(one)
    return (
        ReadRunOperationsUseCase(
            Journal([dispatched, judged]), spend, ceilings, weekly_or_per_run
        ),
        spend,
    )


def request() -> ReadRunOperationsRequest:
    return ReadRunOperationsRequest(workflow_id=WORKFLOW, run_id=RUN, now=AT)


def test_a_run_is_read_with_its_costs_and_its_activity() -> None:
    use_case, _ = reading()
    read = use_case.execute(request())
    assert (read.forge, read.repo, read.spent_usd) == ("github", "o/r", 1.0)
    assert [one.kind for one in read.costs] == [
        "agent_dispatch",
        "model_call",
    ]
    assert [(one.event_type, one.agent_id) for one in read.activity] == [
        ("agent.dispatched", "safety"),
        ("llm.called", ""),
    ]
    # Each cost names the entry it was recorded on.
    assert {one.event_id for one in read.costs} == {
        one.event_id for one in read.activity
    }


def test_an_allowance_per_run_measures_what_the_run_spent_in_its_scope() -> (
    None
):
    use_case, _ = reading(
        SpendBinding(
            scope=SpendScope(forge="github", repo="o/r", agent_id="safety"),
            budget=Budget(usd=0.5),
        ),
        SpendBinding(
            scope=SpendScope(forge="github", repo="o/r"),
            budget=Budget(usd=5.0),
        ),
    )
    checks = use_case.execute(request()).allowances
    measured = [
        (
            one.binding.scope.agent_id,
            one.remaining and one.remaining.spent.usd,
            one.remaining and one.remaining.has_room,
        )
        for one in checks
    ]
    # The most specific allowance first; the reviewer's counts only its
    # own session, the repository's counts the judging too.
    assert measured == [("safety", 0.75, False), ("", 1.0, True)]


def test_a_period_allowance_measures_its_scope_over_the_period() -> None:
    use_case, spend = reading(
        SpendBinding(
            scope=SpendScope(forge="github", repo="o/r"),
            budget=Budget(usd=10.0),
            per="week",
        ),
    )
    spend.costs = [("github", "o/r", "", "", AT - timedelta(hours=3), 4.0)]
    (check,) = use_case.execute(request()).allowances
    assert check.remaining is not None
    assert (
        check.remaining.since,
        check.remaining.until,
        check.remaining.spent.usd,
        check.remaining.left_usd,
    ) == (*WEEK, 5.0, 5.0)


def test_an_allowance_whose_period_cannot_be_found_says_so() -> None:
    use_case, _ = reading(
        SpendBinding(
            scope=SpendScope(forge="github", repo="o/r"),
            budget=Budget(usd=10.0),
            per="month",
        ),
    )
    (check,) = use_case.execute(request()).allowances
    assert (check.remaining, check.unmeasured) == (
        None,
        "nothing says where a month period begins",
    )


def test_a_run_that_recorded_nothing_is_not_found() -> None:
    use_case, _ = reading()
    with pytest.raises(RunNotFoundError):
        use_case.execute(
            ReadRunOperationsRequest(
                workflow_id=WORKFLOW, run_id="another", now=AT
            )
        )
