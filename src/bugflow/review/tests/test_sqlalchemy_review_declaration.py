"""What a repository is reviewed for, against a real database.

Skipped unless DATABASE_URL names a Postgres server. The in-memory
doubles answer the same questions, and the two are kept alike on
purpose.
"""

import uuid

import sqlalchemy as sa

from bugflow.review.domain.models.review_declaration import (
    DispatchedProcesses,
    JudgedPolicies,
)
from bugflow.review.infrastructure.sqlalchemy_review_declaration import (
    SqlAlchemyDispatchedProcesses,
    SqlAlchemyJudgedPolicies,
)


def repo() -> str:
    return f"example/{uuid.uuid4()}"


def test_a_repository_that_declared_nothing_is_judged_on_nothing(
    engine: sa.Engine, database_url: str
) -> None:
    """The default: a repository nobody has decided about costs nothing
    rather than every policy."""
    held = SqlAlchemyJudgedPolicies(database_url)
    assert held.judged("github", repo()) == frozenset()


def test_what_a_repository_declared_is_what_it_is_judged_on(
    engine: sa.Engine, database_url: str
) -> None:
    held = SqlAlchemyJudgedPolicies(database_url)
    name = repo()
    held.declare(
        JudgedPolicies(forge="github", repo=name, policies=("P-01", "P-02"))
    )
    assert held.judged("github", name) == frozenset({"P-01", "P-02"})


def test_declaring_again_replaces_the_set_rather_than_adding(
    engine: sa.Engine, database_url: str
) -> None:
    """A name absent from what the caller sent is a name that is no
    longer declared. A merge would leave it on, which is how a policy
    somebody switched off comes back."""
    held = SqlAlchemyJudgedPolicies(database_url)
    name = repo()
    held.declare(
        JudgedPolicies(forge="github", repo=name, policies=("P-01", "P-02"))
    )
    held.declare(JudgedPolicies(forge="github", repo=name, policies=("P-01",)))
    assert held.judged("github", name) == frozenset({"P-01"})


def test_declaring_nothing_leaves_a_repository_judged_on_nothing(
    engine: sa.Engine, database_url: str
) -> None:
    held = SqlAlchemyJudgedPolicies(database_url)
    name = repo()
    held.declare(JudgedPolicies(forge="github", repo=name, policies=("P-01",)))
    held.declare(JudgedPolicies(forge="github", repo=name))
    assert held.judged("github", name) == frozenset()


def test_one_repositorys_declaration_is_not_anothers(
    engine: sa.Engine, database_url: str
) -> None:
    held = SqlAlchemyJudgedPolicies(database_url)
    mine, theirs = repo(), repo()
    held.declare(JudgedPolicies(forge="github", repo=mine, policies=("P-01",)))
    assert held.judged("github", theirs) == frozenset()


def test_every_declaration_can_be_listed(
    engine: sa.Engine, database_url: str
) -> None:
    held = SqlAlchemyJudgedPolicies(database_url)
    name = repo()
    held.declare(
        JudgedPolicies(forge="github", repo=name, policies=("P-02", "P-01"))
    )
    (mine,) = [one for one in held.declarations() if one.repo == name]
    assert mine.policies == ("P-01", "P-02")


def test_processes_are_declared_the_same_way_and_kept_apart(
    engine: sa.Engine, database_url: str
) -> None:
    """Two interfaces and two tables: a policy declared for a repository
    says nothing about what that repository dispatches."""
    name = repo()
    policies = SqlAlchemyJudgedPolicies(database_url)
    processes = SqlAlchemyDispatchedProcesses(database_url)
    policies.declare(
        JudgedPolicies(forge="github", repo=name, policies=("P-01",))
    )
    processes.declare(
        DispatchedProcesses(
            forge="github",
            repo=name,
            processes=("evaluate-pull-request",),
        )
    )
    assert processes.dispatched("github", name) == frozenset(
        {"evaluate-pull-request"}
    )
    assert policies.judged("github", name) == frozenset({"P-01"})
