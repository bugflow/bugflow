"""Reading what a scope is allowed: what it declares, what it inherits
from the wider scopes that cover it, and what each run in it is handed,
with the allowance each limit comes from."""

from datetime import UTC, datetime, timedelta

from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.dtos.read_allowances import (
    ReadAllowancesRequest,
    ReadAllowancesResponse,
)
from bugflow.review.infrastructure.in_memory_spend_bindings import (
    InMemorySpendBindings,
)
from bugflow.review.infrastructure.in_memory_spend_record import (
    InMemorySpendRecord,
)
from bugflow.review.usecases.read_allowances import ReadAllowancesUseCase
from bugflow.shared.domain.values.budget import Budget, allowance

AT = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
WEEK = (AT - timedelta(days=2), AT + timedelta(days=5))

AGENT = SpendScope(forge="github", repo="o/r", agent_id="safety")
REPOSITORY = SpendScope(forge="github", repo="o/r")
OWNER = SpendScope(forge="github", owner="o")
EVERY_SAFETY = SpendScope(agent_id="safety")
ELSEWHERE = SpendScope(forge="github", repo="o/other")


def weekly(
    binding: SpendBinding, now: datetime
) -> tuple[datetime, datetime] | None:
    return WEEK if binding.per == "week" else None


def reading(
    *bound: tuple[SpendScope, Budget, str],
) -> tuple[ReadAllowancesUseCase, InMemorySpendRecord]:
    ceilings = InMemorySpendBindings()
    for scope, budget, per in bound:
        ceilings.declare(SpendBinding(scope=scope, budget=budget, per=per))
    spend = InMemorySpendRecord()
    return ReadAllowancesUseCase(ceilings, spend, weekly), spend


def read(
    use_case: ReadAllowancesUseCase, scope: SpendScope
) -> ReadAllowancesResponse:
    return use_case.execute(ReadAllowancesRequest(scope=scope, now=AT))


def test_a_scope_inherits_what_every_wider_scope_declares() -> None:
    use_case, _ = reading(
        (AGENT, Budget(usd=1.0, turns=None), "event"),
        (REPOSITORY, Budget(usd=5.0, turns=40), "event"),
        (OWNER, Budget(usd=20.0, turns=None), "week"),
        (EVERY_SAFETY, Budget(usd=0.5, turns=None), "event"),
        (ELSEWHERE, Budget(usd=9.0), "event"),
    )
    held = read(use_case, AGENT)
    assert [(one.check.binding.scope, one.own) for one in held.applied] == [
        (AGENT, True),
        (REPOSITORY, False),
        (OWNER, False),
        (EVERY_SAFETY, False),
    ]
    # The repository reads its own and the owner's, not the agent's.
    assert [
        one.check.binding.scope for one in read(use_case, REPOSITORY).applied
    ] == [
        REPOSITORY,
        OWNER,
    ]


def test_a_runs_ceiling_names_where_each_limit_comes_from() -> None:
    use_case, _ = reading(
        (AGENT, Budget(usd=1.0, turns=None), "event"),
        (REPOSITORY, Budget(usd=5.0, turns=40), "event"),
        (EVERY_SAFETY, Budget(usd=0.5, turns=None), "event"),
    )
    ceiling = read(use_case, AGENT).ceiling
    assert ceiling is not None
    assert ceiling.usd_from is not None and ceiling.turns_from is not None
    assert (ceiling.usd, ceiling.usd_from.scope) == (0.5, EVERY_SAFETY)
    assert (ceiling.turns, ceiling.turns_from.scope) == (40, REPOSITORY)


def test_a_ceiling_is_what_a_dispatch_works_out() -> None:
    bound = [
        Budget(usd=1.0, turns=None),
        Budget(usd=5.0, turns=40),
        Budget(usd=None, turns=80),
    ]
    use_case, _ = reading(
        *(
            (scope, budget, "event")
            for scope, budget in zip(
                (AGENT, REPOSITORY, EVERY_SAFETY), bound, strict=True
            )
        )
    )
    ceiling = read(use_case, AGENT).ceiling
    assert ceiling is not None
    assert Budget(usd=ceiling.usd, turns=ceiling.turns) == allowance(
        bound, None
    )


def test_a_scope_no_allowance_per_event_covers_is_handed_nothing() -> None:
    use_case, _ = reading((REPOSITORY, Budget(usd=5.0), "week"))
    assert read(use_case, AGENT).ceiling is None


def test_an_inherited_period_allowance_measures_its_own_scope() -> None:
    use_case, spend = reading((REPOSITORY, Budget(usd=10.0), "week"))
    spend.costs = [("github", "o/r", "", "", AT - timedelta(hours=1), 4.0)]
    (applied,) = read(use_case, AGENT).applied
    remaining = applied.check.remaining
    assert remaining is not None
    assert (remaining.since, remaining.spent.usd, remaining.left_usd) == (
        WEEK[0],
        4.0,
        6.0,
    )
