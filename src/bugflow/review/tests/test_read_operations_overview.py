"""Reading the operations overview: what each repository spent in a
period, what each allowance has left, most urgent first, and the latest
runs that spent."""

from datetime import UTC, datetime, timedelta

from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.dtos.read_operations_overview import (
    ReadOperationsOverviewRequest,
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
from bugflow.review.usecases.read_operations_overview import (
    ReadOperationsOverviewUseCase,
)
from bugflow.review.usecases.read_repository_operations import (
    ReadRepositoryOperationsUseCase,
)
from bugflow.shared.domain.values.budget import Budget

AT = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
PERIOD = (AT - timedelta(days=7), AT + timedelta(hours=1))
WEEK = (AT - timedelta(days=2), AT + timedelta(days=5))


def window(
    binding: SpendBinding, now: datetime
) -> tuple[datetime, datetime] | None:
    if binding.per == "month":
        raise ValueError("nothing says where a month period begins")
    return WEEK if binding.per == "week" else None


def recorded() -> InMemorySpendRecord:
    spend = InMemorySpendRecord()
    spend.recorded = [
        RecordedCost(
            workflow_id=f"review/{repo}/7",
            run_id=run,
            forge="github",
            repo=repo,
            agent_id="safety",
            kind="agent_dispatch",
            at=AT - timedelta(hours=hours),
            usd=usd,
        )
        for run, repo, hours, usd in (
            ("run-1", "o/r", 1, 2.0),
            ("run-2", "o/r", 2, 1.0),
            ("run-3", "o/other", 3, 4.0),
            ("run-4", "o/r", 30 * 24, 9.0),
        )
    ]
    return spend


def request(recent: int = 20) -> ReadOperationsOverviewRequest:
    return ReadOperationsOverviewRequest(
        since=PERIOD[0], until=PERIOD[1], now=AT, recent=recent
    )


def test_each_repository_is_read_with_what_it_spent_in_the_period() -> None:
    use_case = ReadOperationsOverviewUseCase(
        recorded(), InMemorySpendBindings(), window
    )
    read = use_case.execute(request())
    assert [(one.repo, one.usd, one.runs) for one in read.repositories] == [
        ("o/other", 4.0, 1),
        ("o/r", 3.0, 2),
    ]
    assert read.spent_usd == 7.0


def test_a_repositorys_figure_is_the_one_its_own_page_shows() -> None:
    spend, ceilings = recorded(), InMemorySpendBindings()
    overview = ReadOperationsOverviewUseCase(spend, ceilings, window).execute(
        request()
    )
    for one in overview.repositories:
        own = ReadRepositoryOperationsUseCase(
            InMemoryGnomeSettings(), spend, ceilings, window
        ).execute(
            ReadRepositoryOperationsRequest(
                forge=one.forge,
                repo=one.repo,
                since=PERIOD[0],
                until=PERIOD[1],
                now=AT,
            )
        )
        assert own.spent_usd == one.usd


def test_the_latest_runs_are_listed_and_all_of_them_counted() -> None:
    use_case = ReadOperationsOverviewUseCase(
        recorded(), InMemorySpendBindings(), window
    )
    read = use_case.execute(request(recent=2))
    assert [one.run_id for one in read.recent] == ["run-1", "run-2"]
    assert read.runs == 3


def test_the_allowances_with_least_room_come_first() -> None:
    ceilings = InMemorySpendBindings()
    for scope, usd, per in (
        (SpendScope(forge="github", repo="o/r"), 2.5, "week"),
        (SpendScope(forge="github", repo="o/other"), 100.0, "week"),
        (SpendScope(agent_id="safety"), 1.0, "event"),
        (SpendScope(), None, "week"),
        (SpendScope(forge="github", owner="o"), 50.0, "month"),
        (SpendScope(forge="github"), 5.0, "week"),
    ):
        ceilings.declare(
            SpendBinding(scope=scope, budget=Budget(usd=usd), per=per)
        )
    read = ReadOperationsOverviewUseCase(recorded(), ceilings, window).execute(
        request()
    )
    assert [
        (one.binding.scope, one.binding.per) for one in read.allowances
    ] == [
        # Over: o/r spent 3.0 of 2.5; github spent 7.0 of 5.0.
        (SpendScope(forge="github", repo="o/r"), "week"),
        (SpendScope(forge="github"), "week"),
        (SpendScope(forge="github", owner="o"), "month"),
        (SpendScope(forge="github", repo="o/other"), "week"),
        (SpendScope(), "week"),
        (SpendScope(agent_id="safety"), "event"),
    ]
