"""Reading spend by pace layer or by agent across every repository: what
each spent in a period, the allowances that name it, and the runs each
figure is made of."""

from datetime import UTC, datetime, timedelta

from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.dtos.read_repository_operations import (
    ReadRepositoryOperationsRequest,
)
from bugflow.review.dtos.read_spend_operations import (
    Dimension,
    ReadSpendOperationsRequest,
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
from bugflow.review.usecases.allowance_checks import PER_RUN
from bugflow.review.usecases.read_repository_operations import (
    ReadRepositoryOperationsUseCase,
)
from bugflow.review.usecases.read_spend_operations import (
    ReadSpendOperationsUseCase,
)
from bugflow.shared.domain.values.budget import Budget

AT = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
PERIOD = (AT - timedelta(days=7), AT + timedelta(hours=1))
WEEK = (AT - timedelta(days=1), AT + timedelta(days=6))


def cost(
    run: str, repo: str, usd: float, layer: str = "", agent: str = ""
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


def recorded() -> tuple[InMemorySpendRecord, InMemorySpendBindings]:
    spend = InMemorySpendRecord()
    spend.recorded = [
        cost("run-1", "o/r", 0.75, "service", "safety"),
        cost("run-1", "o/r", 0.25),
        cost("run-22", "o/other", 0.5, "service", "safety"),
        cost("run-333", "o/r", 2.0, "domain", "style"),
    ]
    return spend, InMemorySpendBindings()


def request(
    by: Dimension, name: str | None = None
) -> ReadSpendOperationsRequest:
    return ReadSpendOperationsRequest(
        by=by, name=name, since=PERIOD[0], until=PERIOD[1], now=AT
    )


def test_every_layer_is_read_by_repository_and_agent() -> None:
    spend, ceilings = recorded()
    read = ReadSpendOperationsUseCase(spend, ceilings, weekly).execute(
        request("layer")
    )
    assert [
        (one.repo, one.layer, one.agent_id, one.usd) for one in read.cells
    ] == [
        ("o/r", "domain", "style", 2.0),
        ("o/r", "service", "safety", 0.75),
        ("o/other", "service", "safety", 0.5),
        ("o/r", "", "", 0.25),
    ]
    assert read.spent_usd == 3.5
    # Every run in a period is the overview's to list.
    assert read.runs == ()


def test_one_layer_is_read_with_the_runs_its_figures_are_made_of() -> None:
    spend, ceilings = recorded()
    read = ReadSpendOperationsUseCase(spend, ceilings, weekly).execute(
        request("layer", "service")
    )
    assert [(one.repo, one.usd) for one in read.cells] == [
        ("o/r", 0.75),
        ("o/other", 0.5),
    ]
    assert [(one.run_id, one.repo, one.usd) for one in read.runs] == [
        ("run-1", "o/r", 0.75),
        ("run-22", "o/other", 0.5),
    ]
    assert sum(one.usd for one in read.runs) == read.spent_usd


def test_the_facts_that_name_no_agent_are_read_as_an_agent_of_their_own() -> (
    None
):
    spend, ceilings = recorded()
    read = ReadSpendOperationsUseCase(spend, ceilings, weekly).execute(
        request("agent", "")
    )
    assert [(one.run_id, one.usd) for one in read.runs] == [("run-1", 0.25)]


def test_a_layers_figure_on_a_repository_is_the_repository_pages() -> None:
    spend, ceilings = recorded()
    by_layer = ReadSpendOperationsUseCase(spend, ceilings, weekly).execute(
        request("layer", "service")
    )
    repository = ReadRepositoryOperationsUseCase(
        InMemoryGnomeSettings(), spend, ceilings, weekly
    ).execute(
        ReadRepositoryOperationsRequest(
            forge="github",
            repo="o/r",
            since=PERIOD[0],
            until=PERIOD[1],
            now=AT,
        )
    )
    on_repository = {
        (one.layer, one.agent_id): one.usd for one in repository.spend
    }
    for cell in by_layer.cells:
        if cell.repo == "o/r":
            assert on_repository[(cell.layer, cell.agent_id)] == cell.usd


def test_the_allowances_read_are_those_that_name_the_layer() -> None:
    spend, ceilings = recorded()
    for scope, per in (
        (SpendScope(layer="service"), "week"),
        (SpendScope(layer="service", agent_id="safety"), "event"),
        (SpendScope(layer="domain"), "event"),
        # Covers every layer, so is no allowance of any one of them.
        (SpendScope(forge="github", repo="o/r"), "event"),
    ):
        ceilings.declare(
            SpendBinding(scope=scope, budget=Budget(usd=5.0), per=per)
        )
    use_case = ReadSpendOperationsUseCase(spend, ceilings, weekly)
    service = use_case.execute(request("layer", "service")).allowances
    assert [
        (one.binding.scope.agent_id, one.binding.per) for one in service
    ] == [("safety", "event"), ("", "week")]
    per_run, weekly_check = service
    assert per_run.unmeasured == PER_RUN
    assert weekly_check.remaining is not None
    assert weekly_check.remaining.spent.usd == 1.25
    every = use_case.execute(request("layer")).allowances
    assert {one.binding.scope.layer for one in every} == {"service", "domain"}
