"""A scope's spend, followed down to the runs that produced it.

Every total on a page links to the runs it is made of, so the rows by
run must add up to the total for any scope. The database's own test is
in ``test_sqlalchemy_spend_record``; this holds the double to the same
rule.
"""

from datetime import UTC, datetime, timedelta

from bugflow.review.infrastructure.in_memory_spend_record import (
    InMemorySpendRecord,
    RecordedCost,
)

SINCE = datetime(2026, 11, 2, tzinfo=UTC)
UNTIL = SINCE + timedelta(days=7)


def test_a_scopes_total_is_the_sum_of_its_runs_in_memory() -> None:
    """The double agrees with the database: rows by run add up to the
    scope's figure."""
    record = InMemorySpendRecord()
    at = SINCE + timedelta(hours=1)
    record.recorded = [
        RecordedCost(run_id="a", forge="github", repo="o/r", at=at, usd=0.25),
        RecordedCost(
            run_id="a",
            forge="github",
            repo="o/r",
            agent_id="safety",
            kind="agent_dispatch",
            at=at,
            usd=0.5,
        ),
        RecordedCost(
            run_id="b",
            forge="github",
            repo="o/r",
            layer="weekly",
            agent_id="safety",
            kind="stocktake_review",
            at=at + timedelta(hours=1),
            usd=2.0,
        ),
    ]
    for scope in (
        {"repo": "o/r"},
        {"agent_id": "safety"},
        {"layer": "weekly"},
    ):
        total = record.spent(SINCE, UNTIL, **scope)
        rows = record.spent_by_run(SINCE, UNTIL, **scope)
        assert (
            sum(row.usd for row in rows),
            sum(row.facts for row in rows),
        ) == (
            total.usd,
            total.facts,
        ), scope
    assert record.spent_by_run(SINCE, UNTIL)[0].run_id == "b"
