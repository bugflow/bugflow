"""The deployments this server was sent, against a real database.

Skipped unless DATABASE_URL names a Postgres server. The in-memory
store answers the same questions in ``test_a_policy_deployment``, and
the two are kept alike on purpose.

The tables hold one history for the whole server, so each test reads
what it put there itself and asserts nothing about what came before.
"""

import uuid

import pytest
import sqlalchemy as sa

from bugflow.method.domain.errors import PolicyDeploymentConflictError
from bugflow.method.domain.models.policy_deployment import (
    DeployedFile,
    PolicyDeployment,
)
from bugflow.method.infrastructure.sqlalchemy_policy_deployments import (
    SqlAlchemyPolicyDeployments,
)


def deployment(repository: str, commit: str, text: str) -> PolicyDeployment:
    return PolicyDeployment(
        repository=repository,
        commit=commit,
        files=(
            DeployedFile(path="prose/reviewer.md", text=text),
            DeployedFile(path="pace-layers.toml", text="topology\n"),
        ),
    )


def repository() -> str:
    return f"example/{uuid.uuid4()}"


def test_the_deployment_sent_last_is_in_force_with_its_files(
    engine: sa.Engine, database_url: str
) -> None:
    held = SqlAlchemyPolicyDeployments(database_url)
    name = repository()
    assert held.deploy(deployment(name, "c1", "one\n")) is True
    assert held.deploy(deployment(name, "c2", "two\n")) is True
    in_force = held.in_force()
    assert in_force == deployment(name, "c2", "two\n")
    assert [put.commit for put in held.history()[:2]] == ["c2", "c1"]
    assert held.history()[0].content_hash == in_force.content_hash


def test_sending_the_one_in_force_again_changes_nothing(
    engine: sa.Engine, database_url: str
) -> None:
    held = SqlAlchemyPolicyDeployments(database_url)
    name = repository()
    held.deploy(deployment(name, "c1", "one\n"))
    before = len(held.history())
    assert held.deploy(deployment(name, "c1", "one\n")) is False
    assert len(held.history()) == before


def test_sending_an_earlier_one_again_puts_it_back_in_force(
    engine: sa.Engine, database_url: str
) -> None:
    held = SqlAlchemyPolicyDeployments(database_url)
    name = repository()
    held.deploy(deployment(name, "c1", "one\n"))
    held.deploy(deployment(name, "c2", "two\n"))
    assert held.deploy(deployment(name, "c1", "one\n")) is True
    in_force = held.in_force()
    assert in_force is not None and in_force.commit == "c1"


def test_a_commit_held_with_other_content_is_refused(
    engine: sa.Engine, database_url: str
) -> None:
    held = SqlAlchemyPolicyDeployments(database_url)
    name = repository()
    held.deploy(deployment(name, "c1", "one\n"))
    with pytest.raises(PolicyDeploymentConflictError):
        held.deploy(deployment(name, "c1", "something else\n"))
    kept = held.held(name, "c1")
    assert kept is not None
    assert kept.text_of("prose/reviewer.md") == "one\n"


def test_a_commit_never_sent_is_not_held(
    engine: sa.Engine, database_url: str
) -> None:
    held = SqlAlchemyPolicyDeployments(database_url)
    assert held.held(repository(), "c1") is None


def test_the_last_put_in_force_names_the_deployment_in_force(
    engine: sa.Engine, database_url: str
) -> None:
    held = SqlAlchemyPolicyDeployments(database_url)
    name = repository()
    held.deploy(deployment(name, "c1", "one\n"))
    held.deploy(deployment(name, "c2", "two\n"))
    latest = held.last_put_in_force()
    assert latest is not None
    assert (latest.repository, latest.commit) == (name, "c2")
    assert latest.content_hash == deployment(name, "c2", "two\n").content_hash
    assert latest == held.history()[0]
