"""Governance in Postgres: the deployment's default, overridden per
repository.

Skipped unless DATABASE_URL names a Postgres server.
"""

import uuid

import sqlalchemy as sa

from bugflow.review.infrastructure.sqlalchemy_governance import (
    SqlAlchemyGovernance,
    governance,
)

DEFAULT = ("style", "safety")


def repo_name() -> str:
    return f"example/{uuid.uuid4().hex[:12]}"


def decide(
    engine: sa.Engine, forge: str, repo: str, agent_id: str, governs: bool
) -> None:
    with engine.begin() as connection:
        connection.execute(
            governance.insert().values(
                forge=forge, repo=repo, agent_id=agent_id, governs=governs
            )
        )


def test_a_repository_nobody_decided_about_takes_the_default(
    engine: sa.Engine, database_url: str
) -> None:
    store = SqlAlchemyGovernance(database_url, DEFAULT)
    assert store.governing_agents("github", repo_name()) == frozenset(DEFAULT)


def test_an_agent_switched_off_stops_governing_that_repository(
    engine: sa.Engine, database_url: str
) -> None:
    repo = repo_name()
    decide(engine, "github", repo, "safety", False)
    store = SqlAlchemyGovernance(database_url, DEFAULT)
    assert store.governing_agents("github", repo) == frozenset({"style"})


def test_an_agent_switched_on_governs_beyond_the_default(
    engine: sa.Engine, database_url: str
) -> None:
    repo = repo_name()
    decide(engine, "github", repo, "architecture", True)
    store = SqlAlchemyGovernance(database_url, ("style",))
    assert store.governing_agents("github", repo) == frozenset(
        {"style", "architecture"}
    )


def test_a_decision_on_one_forge_leaves_the_other_alone(
    engine: sa.Engine, database_url: str
) -> None:
    repo = repo_name()
    decide(engine, "forgejo", repo, "safety", False)
    store = SqlAlchemyGovernance(database_url, DEFAULT)
    assert store.governing_agents("github", repo) == frozenset(DEFAULT)
