"""GovernanceService's contract, run against every adapter.

Both adapters answer the same question: which agents govern a
repository's review label. A decision merges with the deployment's
default: one to govern adds an agent beyond it, one not to removes it,
and a repository nobody decided about takes the default whole.

The in-memory half takes its decisions frozen at construction, so this
builds each adapter from recorded decisions rather than mutating a live
store: that is the shape both a staged rollout's read and a replay's
fixed data have. The Postgres half is a live store, decided into before
the adapter is built.

The Postgres half is skipped unless DATABASE_URL names a Postgres
server. The in-memory half needs nothing running.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

import pytest
import sqlalchemy as sa

from bugflow.review.domain.services.governance import GovernanceService
from bugflow.review.infrastructure.in_memory_governance import (
    InMemoryGovernance,
)
from bugflow.review.infrastructure.sqlalchemy_governance import (
    SqlAlchemyGovernance,
)
from bugflow.review.infrastructure.sqlalchemy_governance import (
    governance as governance_table,
)

DEFAULT = ("style", "safety")


def repo_name() -> str:
    return f"example/{uuid.uuid4().hex[:12]}"


class GovernanceBackend(Protocol):
    def decide(
        self, forge: str, repo: str, agent_id: str, governs: bool
    ) -> None:
        """Record a decision, as an operator switching an agent on or off
        for a repository would."""
        ...

    def build(self, default: Iterable[str]) -> GovernanceService:
        """Return a store answering governing_agents for what was
        decided so far, with default for everything nobody decided
        about."""
        ...


@dataclass
class InMemoryBackend:
    """Applies the same merge SqlAlchemyGovernance computes at read time
    (default, plus an agent switched on, minus one switched off) and
    bakes the result into the overrides InMemoryGovernance is built
    with."""

    decisions: dict[tuple[str, str], dict[str, bool]] = field(
        default_factory=dict
    )

    def decide(
        self, forge: str, repo: str, agent_id: str, governs: bool
    ) -> None:
        self.decisions.setdefault((forge, repo), {})[agent_id] = governs

    def build(self, default: Iterable[str]) -> GovernanceService:
        base = frozenset(default)
        overrides: dict[tuple[str, str], frozenset[str]] = {}
        for key, decided in self.decisions.items():
            agents = set(base)
            for agent_id, governs in decided.items():
                if governs:
                    agents.add(agent_id)
                else:
                    agents.discard(agent_id)
            overrides[key] = frozenset(agents)
        return InMemoryGovernance(default=base, overrides=overrides)


@dataclass
class SqlAlchemyBackend:
    engine: sa.Engine
    database_url: str

    def decide(
        self, forge: str, repo: str, agent_id: str, governs: bool
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                governance_table.insert().values(
                    forge=forge, repo=repo, agent_id=agent_id, governs=governs
                )
            )

    def build(self, default: Iterable[str]) -> GovernanceService:
        return SqlAlchemyGovernance(self.database_url, default)


@pytest.fixture(params=["in_memory", "sqlalchemy"])
def backend(request: pytest.FixtureRequest) -> GovernanceBackend:
    if request.param == "in_memory":
        return InMemoryBackend()
    # Requested lazily, so the in-memory half above never triggers the
    # Postgres skip or the scripts it runs.
    database_url = request.getfixturevalue("database_url")
    engine = request.getfixturevalue("engine")
    return SqlAlchemyBackend(engine=engine, database_url=database_url)


def test_a_repository_nobody_decided_about_takes_the_default(
    backend: GovernanceBackend,
) -> None:
    governance = backend.build(DEFAULT)
    assert governance.governing_agents("github", repo_name()) == frozenset(
        DEFAULT
    )


def test_an_agent_switched_off_stops_governing_that_repository(
    backend: GovernanceBackend,
) -> None:
    repo = repo_name()
    backend.decide("github", repo, "safety", False)
    governance = backend.build(DEFAULT)
    assert governance.governing_agents("github", repo) == frozenset({"style"})


def test_an_agent_switched_on_governs_beyond_the_default(
    backend: GovernanceBackend,
) -> None:
    repo = repo_name()
    backend.decide("github", repo, "architecture", True)
    governance = backend.build(("style",))
    assert governance.governing_agents("github", repo) == frozenset(
        {"style", "architecture"}
    )


def test_a_decision_on_one_forge_leaves_the_other_alone(
    backend: GovernanceBackend,
) -> None:
    repo = repo_name()
    backend.decide("forgejo", repo, "safety", False)
    governance = backend.build(DEFAULT)
    assert governance.governing_agents("github", repo) == frozenset(DEFAULT)
