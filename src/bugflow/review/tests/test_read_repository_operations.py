"""Reading one repository for the operations pages: what each gnome is
set to do there, the allowances that cover it, what it spent in a
period by layer and agent, and the runs each figure is made of."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from bugflow.review.domain.models.gnome_setting import GnomeSetting
from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.dtos.read_repository_operations import (
    ReadRepositoryOperationsRequest,
)
from bugflow.review.infrastructure.in_memory_gnome_settings import (
    InMemoryGnomeSettings,
)
from bugflow.review.infrastructure.in_memory_spend_bindings import (
    InMemorySpendBindings,
)
from bugflow.review.infrastructure.in_memory_spend_record import (
    InMemorySpendRecord,
    RecordedCost,
)
from bugflow.review.usecases.read_repository_operations import (
    PER_RUN,
    ReadRepositoryOperationsUseCase,
)
from bugflow.shared.domain.values.budget import Budget

AT = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
PERIOD = (AT - timedelta(days=7), AT + timedelta(hours=1))
WEEK = (AT - timedelta(days=1), AT + timedelta(days=6))


def cost(
    run: str, usd: float, agent: str = "", layer: str = "", repo: str = "o/r"
) -> RecordedCost:
    return RecordedCost(
        workflow_id=f"review/{repo}/7",
        run_id=run,
        forge="github",
        repo=repo,
        layer=layer,
        agent_id=agent,
        kind="agent_dispatch" if agent else "model_call",
        at=AT - timedelta(minutes=len(run)),
        usd=usd,
    )


def weekly(
    binding: SpendBinding, now: datetime
) -> tuple[datetime, datetime] | None:
    return WEEK if binding.per == "week" else None


def reading(
    *bindings: SpendBinding,
) -> ReadRepositoryOperationsUseCase:
    spend = InMemorySpendRecord()
    spend.recorded = [
        cost("run-1", 0.75, agent="safety", layer="service"),
        cost("run-1", 0.25),
        cost("run-22", 0.5, agent="safety", layer="service"),
        cost("run-333", 2.0, agent="style", layer="service"),
        cost("run-4444", 9.0, agent="safety", repo="o/elsewhere"),
    ]
    ceilings = InMemorySpendBindings()
    for one in bindings:
        ceilings.declare(one)
    settings = InMemoryGnomeSettings(
        GnomeSetting(
            forge="github", repo="o/r", gnome="safety", behaviour="gate"
        ),
        GnomeSetting(
            forge="github",
            repo="o/elsewhere",
            gnome="style",
            behaviour="advise",
        ),
    )
    return ReadRepositoryOperationsUseCase(settings, spend, ceilings, weekly)


def request(
    layer: str | None = None, agent_id: str | None = None
) -> ReadRepositoryOperationsRequest:
    return ReadRepositoryOperationsRequest(
        forge="github",
        repo="o/r",
        since=PERIOD[0],
        until=PERIOD[1],
        now=AT,
        layer=layer,
        agent_id=agent_id,
    )


def test_a_repository_is_read_with_its_settings_and_spend_by_agent() -> None:
    read = reading().execute(request())
    assert [(one.gnome, one.behaviour) for one in read.settings] == [
        ("safety", "gate")
    ]
    assert [
        (one.layer, one.agent_id, one.usd, one.runs) for one in read.spend
    ] == [
        ("service", "style", 2.0, 1),
        ("service", "safety", 1.25, 2),
        ("", "", 0.25, 1),
    ]
    assert read.spent_usd == 3.5


def test_each_spend_rows_total_is_the_sum_of_the_runs_listed_for_it() -> None:
    use_case = reading()
    for row in use_case.execute(request()).spend:
        runs = use_case.execute(request(row.layer, row.agent_id)).runs
        assert sum(one.usd for one in runs) == row.usd
        assert len(runs) == row.runs


def test_the_runs_of_a_spend_row_are_those_its_facts_came_from() -> None:
    read = reading().execute(request(layer="service", agent_id="safety"))
    assert [(one.run_id, one.usd) for one in read.runs] == [
        ("run-1", 0.75),
        ("run-22", 0.5),
    ]
    # Facts that name no agent are a row of their own.
    unnamed = reading().execute(request(layer="", agent_id=""))
    assert [(one.run_id, one.usd) for one in unnamed.runs] == [("run-1", 0.25)]


def test_every_run_is_listed_when_no_spend_row_is_named() -> None:
    read = reading().execute(request())
    assert [(one.run_id, one.usd) for one in read.runs] == [
        ("run-1", 1.0),
        ("run-22", 0.5),
        ("run-333", 2.0),
    ]


def test_the_allowances_that_reach_the_repository_are_measured() -> None:
    read = reading(
        SpendBinding(
            scope=SpendScope(forge="github", repo="o/r"),
            budget=Budget(usd=10.0),
            per="week",
        ),
        SpendBinding(
            scope=SpendScope(agent_id="safety"), budget=Budget(usd=1.0)
        ),
        SpendBinding(
            scope=SpendScope(forge="github", repo="o/elsewhere"),
            budget=Budget(usd=1.0),
        ),
    ).execute(request())
    weekly_check, per_run_check = read.allowances
    assert weekly_check.remaining is not None
    assert (
        weekly_check.remaining.since,
        weekly_check.remaining.until,
        weekly_check.remaining.spent.usd,
        weekly_check.remaining.left_usd,
    ) == (*WEEK, 3.5, 6.5)
    assert (
        per_run_check.binding.scope.agent_id,
        per_run_check.unmeasured,
    ) == (
        "safety",
        PER_RUN,
    )


def test_a_period_ends_after_it_begins() -> None:
    with pytest.raises(ValidationError, match="ends after it begins"):
        ReadRepositoryOperationsRequest(
            forge="github", repo="o/r", since=AT, until=AT, now=AT
        )
