"""The deployments this server was sent, against a real database.

Skipped unless DATABASE_URL names a Postgres server. The in-memory
store answers the same questions in ``test_a_policy_deployment``, and
the two are kept alike on purpose.

The tables hold one history for the whole server, so each test reads
what it put there itself and asserts nothing about what came before.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from bugflow.method.domain.errors import PolicyDeploymentConflictError
from bugflow.method.domain.facts import POLICIES_DEPLOYED
from bugflow.method.domain.models.policy_deployment import (
    DeployedFile,
    PolicyDeployment,
    PutInForce,
)
from bugflow.method.infrastructure.sqlalchemy_policy_deployments import (
    SqlAlchemyPolicyDeployments,
    deployments,
    files,
    in_force,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.infrastructure.sqlalchemy_journal import (
    SqlAlchemyJournal,
    journal,
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


def puts(engine: sa.Engine, name: str) -> list[str]:
    """The commits of the repository put in force, in the order they
    were, read from the table."""
    with engine.connect() as connection:
        return list(
            connection.execute(
                sa.select(in_force.c.commit)
                .where(in_force.c.repository == name)
                .order_by(in_force.c.id)
            ).scalars()
        )


def kept(engine: sa.Engine, name: str, commit: str) -> dict[str, str] | None:
    """The files the tables keep for that repository and commit, by
    path, or None if they keep no such deployment."""
    with engine.connect() as connection:
        known = connection.execute(
            sa.select(deployments.c.commit).where(
                deployments.c.repository == name,
                deployments.c.commit == commit,
            )
        ).one_or_none()
        if known is None:
            return None
        rows = connection.execute(
            sa.select(files.c.path, files.c.text).where(
                files.c.repository == name, files.c.commit == commit
            )
        )
        return {row.path: row.text for row in rows}


def test_the_deployment_sent_last_is_in_force_with_its_files(
    engine: sa.Engine, database_url: str
) -> None:
    held = SqlAlchemyPolicyDeployments(database_url)
    name = repository()
    assert held.deploy(deployment(name, "c1", "one\n")) is True
    assert held.deploy(deployment(name, "c2", "two\n")) is True
    assert held.in_force() == deployment(name, "c2", "two\n")
    assert puts(engine, name) == ["c1", "c2"]


def test_sending_the_one_in_force_again_changes_nothing(
    engine: sa.Engine, database_url: str
) -> None:
    held = SqlAlchemyPolicyDeployments(database_url)
    name = repository()
    held.deploy(deployment(name, "c1", "one\n"))
    assert held.deploy(deployment(name, "c1", "one\n")) is False
    assert puts(engine, name) == ["c1"]


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
    stored = kept(engine, name, "c1")
    assert stored is not None
    assert stored["prose/reviewer.md"] == "one\n"


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


def fact(name: str, replaced: PutInForce | None) -> list[JournalEntry]:
    return [
        JournalEntry(
            event_id=uuid.uuid4(),
            occurred_at=datetime.now(UTC),
            event_type=POLICIES_DEPLOYED,
            forge="",
            repo="",
            pr_number=None,
            commit_sha=None,
            corpus_version=None,
            workflow_id="policies/deploy",
            run_id=f"{name}@c1",
            payload={
                "repository": name,
                "commit": "c1",
                "content_hash": "",
                "files": 2,
                "sent_by": "a test",
                "replaced": None
                if replaced is None
                else {
                    "repository": replaced.repository,
                    "commit": replaced.commit,
                    "content_hash": replaced.content_hash,
                },
            },
        )
    ]


def recorded(engine: sa.Engine, name: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                sa.select(sa.func.count()).where(
                    journal.c.event_type == POLICIES_DEPLOYED,
                    journal.c.run_id == f"{name}@c1",
                )
            ).scalar_one()
        )


def test_the_fact_is_recorded_with_the_deployment(
    engine: sa.Engine, database_url: str
) -> None:
    held = SqlAlchemyPolicyDeployments(
        database_url, SqlAlchemyJournal(database_url)
    )
    name = repository()
    assert held.deploy(
        deployment(name, "c1", "one\n"), lambda was: fact(name, was)
    )
    assert recorded(engine, name) == 1


class RefusingJournal:
    def append_on(
        self, connection: sa.Connection, entries: Sequence[JournalEntry]
    ) -> None:
        raise RuntimeError("the journal refuses")


def test_a_deployment_whose_fact_is_not_recorded_is_not_put_in_force(
    engine: sa.Engine, database_url: str
) -> None:
    """Sent again, it is put in force and recorded then, rather than
    answered as already in force with no fact."""
    name = repository()
    refusing = SqlAlchemyPolicyDeployments(database_url, RefusingJournal())
    with pytest.raises(RuntimeError, match="the journal refuses"):
        refusing.deploy(
            deployment(name, "c1", "one\n"), lambda was: fact(name, was)
        )
    assert kept(engine, name, "c1") is None
    assert puts(engine, name) == []

    held = SqlAlchemyPolicyDeployments(
        database_url, SqlAlchemyJournal(database_url)
    )
    assert held.deploy(
        deployment(name, "c1", "one\n"), lambda was: fact(name, was)
    )
    assert recorded(engine, name) == 1


def test_a_store_with_no_journal_refuses_a_deployment_with_facts(
    engine: sa.Engine, database_url: str
) -> None:
    held, name = SqlAlchemyPolicyDeployments(database_url), repository()
    with pytest.raises(ValueError, match="no journal"):
        held.deploy(
            deployment(name, "c1", "one\n"), lambda was: fact(name, was)
        )
    assert kept(engine, name, "c1") is None
