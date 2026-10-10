"""Tests of when a run may judge no more, and why it stopped.

Judging is spending and is capped like any other. The ceiling is the
allowance per run covering the repository with no reviewer named, since
judging is the evaluation itself and names none. What the run has spent
is every cost it recorded.
"""

from bugflow.apps.worker.reviewers import judging_over_ceiling
from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.infrastructure.in_memory_spend_bindings import (
    InMemorySpendBindings,
)
from bugflow.review.infrastructure.in_memory_spend_record import (
    InMemorySpendRecord,
)
from bugflow.shared.domain.values.budget import Budget

RUN = "0d9a2f6c-1b3e-4a77-9c21-2b9a7f0e5d18"
REPO = SpendScope(forge="github", repo="o/r")


def bound(
    usd: float | None, per: str = "event", scope: SpendScope = REPO
) -> InMemorySpendBindings:
    held = InMemorySpendBindings()
    held.declare(
        SpendBinding(scope=scope, budget=Budget(usd=usd, turns=None), per=per)
    )
    return held


def spent(usd: float, run_id: str = RUN) -> InMemorySpendRecord:
    held = InMemorySpendRecord()
    held.run_costs = [(run_id, usd)]
    return held


def over(
    ceilings: InMemorySpendBindings | None,
    record: InMemorySpendRecord | None,
    run_id: str = RUN,
) -> str | None:
    return judging_over_ceiling(ceilings, record, run_id, "github", "o/r")


def test_a_run_under_its_ceiling_may_judge() -> None:
    assert over(bound(2.50), spent(1.10)) is None


def test_a_run_at_its_ceiling_may_not() -> None:
    refusal = over(bound(2.50), spent(2.50))

    assert refusal is not None
    assert "$2.50" in refusal


def test_the_refusal_says_what_was_allowed_and_what_went() -> None:
    refusal = over(bound(2.50), spent(3.75))

    assert refusal == "this run is allowed $2.50 and has spent $3.75"


def test_a_run_that_has_recorded_nothing_may_judge() -> None:
    assert over(bound(2.50), InMemorySpendRecord()) is None


def test_another_run_s_spending_is_not_this_run_s() -> None:
    elsewhere = spent(9.99, run_id="8e1c3a40-5f22-4d9b-b0aa-6c4e71d2f993")

    assert over(bound(2.50), elsewhere) is None


def test_the_lowest_of_several_ceilings_holds_the_run() -> None:
    held = bound(2.50)
    held.declare(
        SpendBinding(
            scope=SpendScope(forge="github"),
            budget=Budget(usd=1.00, turns=None),
            per="event",
        )
    )

    refusal = over(held, spent(1.20))

    assert refusal is not None
    assert "$1.00" in refusal


def test_a_period_allowance_is_not_a_run_s_ceiling() -> None:
    """A week's allowance says whether the run happens, not what it may
    spend once it does."""
    assert over(bound(150.0, per="weekly"), spent(9.99)) is None


def test_an_allowance_naming_a_reviewer_does_not_hold_the_judge() -> None:
    """Judging names no reviewer, so a reviewer's allowance is not its
    ceiling: the evaluation is not that agent's run."""
    reviewer = bound(
        0.50, scope=SpendScope(forge="github", repo="o/r", agent_id="security")
    )

    assert over(reviewer, spent(1.20)) is None


def test_an_unlimited_allowance_holds_the_run_to_nothing() -> None:
    assert over(bound(None), spent(99.0)) is None


def test_a_deployment_with_no_record_is_not_over_every_limit() -> None:
    assert over(bound(2.50), None) is None
    assert over(None, spent(99.0)) is None


def test_a_run_with_no_id_is_not_held() -> None:
    """An activity outside a workflow has no run to measure."""
    assert over(bound(2.50), spent(99.0), run_id="") is None
