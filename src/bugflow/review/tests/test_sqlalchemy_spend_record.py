"""What this deployment spent, against a real database.

Skipped unless DATABASE_URL names a Postgres server. Two kinds of fact
carry a cost and carry it differently: a delegated run's session cost in
dollars, a model call's in nanodollars. Both are read here, because a
dispatcher refusing a run and a page showing the month have to agree on
one number.
"""

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from bugflow.review.infrastructure.sqlalchemy_spend_record import (
    SqlAlchemySpendRecord,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal

AT = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
WINDOW = (AT - timedelta(hours=1), AT + timedelta(hours=1))


def repo() -> str:
    return f"example/{uuid.uuid4()}"


def entry(
    repo: str,
    event_type: str,
    payload: dict[str, object],
    *,
    at: datetime = AT,
    agent: str | None = "safety",
    run_id: str | None = None,
) -> JournalEntry:
    return JournalEntry(
        event_id=uuid.uuid4(),
        occurred_at=at,
        event_type=event_type,
        forge="github",
        repo=repo,
        pr_number=None,
        commit_sha=None,
        corpus_version=None,
        workflow_id="test/spend",
        run_id=run_id or str(uuid.uuid4()),
        payload=payload,
        agent_id=agent,
    )


def test_a_runs_session_cost_is_counted_in_dollars(
    engine: sa.Engine, database_url: str
) -> None:
    name = repo()
    SqlAlchemyJournal(database_url).append(
        [
            entry(
                name,
                "stocktake.reviewed",
                {"layer": "weekly", "cost": {"usd": 1.3}},
            ),
        ]
    )
    spent = SqlAlchemySpendRecord(database_url).spent(*WINDOW, repo=name)
    assert (round(spent.usd, 4), spent.facts) == (1.3, 1)


def test_a_model_calls_nanodollars_are_counted_as_dollars(
    engine: sa.Engine, database_url: str
) -> None:
    """The proxy's figures are kept as integers so a million summed is
    still exact, and a ceiling is in dollars."""
    name = repo()
    SqlAlchemyJournal(database_url).append(
        [
            entry(name, "llm.called", {"cost_nanodollars": 250_000_000}),
            entry(name, "llm.called", {"cost_nanodollars": 750_000_000}),
        ]
    )
    spent = SqlAlchemySpendRecord(database_url).spent(*WINDOW, repo=name)
    assert (round(spent.usd, 4), spent.facts) == (1.0, 2)


def test_both_kinds_of_cost_are_one_figure(
    engine: sa.Engine, database_url: str
) -> None:
    name = repo()
    SqlAlchemyJournal(database_url).append(
        [
            entry(name, "llm.called", {"cost_nanodollars": 500_000_000}),
            entry(
                name,
                "agent.dispatched",
                {"layer": "pull-request", "cost": {"usd": 0.31}},
            ),
        ]
    )
    spent = SqlAlchemySpendRecord(database_url).spent(*WINDOW, repo=name)
    assert (round(spent.usd, 4), spent.facts) == (0.81, 2)


def test_a_window_nothing_ran_in_is_zero_over_no_facts(
    engine: sa.Engine, database_url: str
) -> None:
    """Which is not the same as a window nobody asked about: a caller
    that cannot tell the two apart refuses a dispatch on a missing row."""
    spent = SqlAlchemySpendRecord(database_url).spent(*WINDOW, repo=repo())
    assert (spent.usd, spent.facts) == (0.0, 0)


def test_only_what_the_scope_names_is_counted(
    engine: sa.Engine, database_url: str
) -> None:
    name = repo()
    SqlAlchemyJournal(database_url).append(
        [
            entry(
                name,
                "stocktake.reviewed",
                {"layer": "weekly", "cost": {"usd": 2.0}},
            ),
            entry(
                name,
                "agent.dispatched",
                {"layer": "pull-request", "cost": {"usd": 5.0}},
            ),
        ]
    )
    record = SqlAlchemySpendRecord(database_url)
    weekly = record.spent(*WINDOW, repo=name, layer="weekly")
    assert (round(weekly.usd, 4), weekly.facts) == (2.0, 1)
    mine = record.spent(*WINDOW, repo=name, agent_id="safety")
    assert round(mine.usd, 4) == 7.0
    theirs = record.spent(*WINDOW, repo=name, agent_id="style")
    assert theirs.facts == 0


def test_a_cost_outside_the_window_is_not_counted(
    engine: sa.Engine, database_url: str
) -> None:
    name = repo()
    SqlAlchemyJournal(database_url).append(
        [
            entry(
                name,
                "stocktake.reviewed",
                {"layer": "weekly", "cost": {"usd": 4.0}},
                at=AT - timedelta(days=2),
            ),
        ]
    )
    spent = SqlAlchemySpendRecord(database_url).spent(*WINDOW, repo=name)
    assert spent.facts == 0


def test_a_checked_policys_cost_is_counted_like_any_other(
    engine: sa.Engine, database_url: str
) -> None:
    """How a policy reaches its answer is the policy's business. The
    spend reader counts what a fact says it cost, whatever produced
    it."""
    name = repo()
    SqlAlchemyJournal(database_url).append(
        [
            entry(
                name,
                "policy.checked",
                {"policy_id": "P-01", "cost": {"usd": 1e-08}},
            ),
        ]
    )
    spent = SqlAlchemySpendRecord(database_url).spent(*WINDOW, repo=name)
    assert spent.facts == 1
    assert spent.usd > 0


def test_a_runs_own_spending_is_read_by_its_run_id(
    engine: sa.Engine, database_url: str
) -> None:
    """A per-event ceiling holds one run, so what that run spent is
    asked for by its id and nothing else is counted."""
    name = repo()
    run = str(uuid.uuid4())
    SqlAlchemyJournal(database_url).append(
        [
            entry(
                name,
                "llm.called",
                {"cost_nanodollars": 400_000_000},
                run_id=run,
            ),
            entry(
                name,
                "agent.dispatched",
                {"layer": "pull-request", "cost": {"usd": 0.31}},
                run_id=run,
            ),
            entry(name, "llm.called", {"cost_nanodollars": 900_000_000}),
        ]
    )

    spent = SqlAlchemySpendRecord(database_url).spent_in_run(run)

    assert (round(spent.usd, 4), spent.facts) == (0.71, 2)


def test_a_run_that_recorded_no_cost_is_zero_over_no_facts(
    engine: sa.Engine, database_url: str
) -> None:
    spent = SqlAlchemySpendRecord(database_url).spent_in_run(str(uuid.uuid4()))

    assert (spent.usd, spent.facts) == (0.0, 0)


def test_spend_is_read_through_the_relation_named(
    engine: sa.Engine, database_url: str
) -> None:
    """A deployment that keeps a view over the journal reads spend
    through it, so a row the view leaves out is not counted."""
    name = repo()
    SqlAlchemyJournal(database_url).append(
        [
            entry(
                name,
                "stocktake.reviewed",
                {"layer": "weekly", "cost": {"usd": 9.0}},
            ),
        ]
    )
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "create or replace view journal_of_nothing as "
                "select * from journal where false"
            )
        )
    through_view = SqlAlchemySpendRecord(database_url, "journal_of_nothing")
    through_table = SqlAlchemySpendRecord(database_url)
    assert through_view.spent(*WINDOW, repo=name).facts == 0
    assert through_table.spent(*WINDOW, repo=name).facts == 1
