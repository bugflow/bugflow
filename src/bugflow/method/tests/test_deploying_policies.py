"""Tests of the use case that keeps a deployment and puts it in force:
what it stores, what it records, and what it refuses."""

from datetime import UTC, datetime

import pytest

from bugflow.method.domain.errors import (
    PolicyDeploymentConflictError,
    PolicyDeploymentError,
)
from bugflow.method.domain.facts import POLICIES_DEPLOYED
from bugflow.method.dtos.deploy_policies import (
    DeployPoliciesRequest,
    PolicyFile,
)
from bugflow.method.infrastructure.in_memory_policy_deployments import (
    InMemoryPolicyDeployments,
)
from bugflow.method.infrastructure.policy_deployment_parsing import (
    ParsedPolicyDeploymentCheck,
)
from bugflow.method.tests.policy_files import MANIFEST, READ
from bugflow.method.usecases.deploy_policies import DeployPoliciesUseCase
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal

REPOSITORY = "example-org/pull-request-policies"
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.at = NOW

    def now(self) -> datetime:
        return self.at


class Fixture:
    def __init__(self) -> None:
        self.deployments = InMemoryPolicyDeployments()
        self.journal = InMemoryJournal()
        self.clock = Clock()
        self.deploy = DeployPoliciesUseCase(
            self.deployments,
            ParsedPolicyDeploymentCheck(),
            self.journal,
            self.clock,
        )


def request(
    commit: str = "c1",
    files: dict[str, str] | None = None,
    check_only: bool = False,
) -> DeployPoliciesRequest:
    return DeployPoliciesRequest(
        repository=REPOSITORY,
        commit=commit,
        files=tuple(
            PolicyFile(path=path, text=text)
            for path, text in (READ if files is None else files).items()
        ),
        check_only=check_only,
        sent_by="a test",
    )


def edited(note: str) -> dict[str, str]:
    return READ | {"prose/reviewer.md": MANIFEST + note}


def test_a_deployment_is_stored_put_in_force_and_recorded() -> None:
    fixture = Fixture()
    answered = fixture.deploy.execute(request())
    assert answered.outcome == "deployed"
    assert answered.in_force is not None
    assert answered.in_force.commit == "c1"
    assert answered.in_force.content_hash == answered.content_hash
    in_force = fixture.deployments.in_force()
    assert in_force is not None and len(in_force.files) == len(READ)
    (fact,) = fixture.journal.entries
    assert fact.event_type == POLICIES_DEPLOYED
    assert (fact.forge, fact.repo, fact.pr_number) == ("", "", None)
    assert fact.occurred_at == NOW
    assert fact.payload == {
        "repository": REPOSITORY,
        "commit": "c1",
        "content_hash": answered.content_hash,
        "files": len(READ),
        "sent_by": "a test",
        "replaced": None,
    }


def test_sending_the_one_in_force_again_records_nothing() -> None:
    fixture = Fixture()
    fixture.deploy.execute(request())
    answered = fixture.deploy.execute(request())
    assert answered.outcome == "already_in_force"
    assert len(fixture.journal.entries) == 1


def test_the_fact_names_the_deployment_that_was_replaced() -> None:
    fixture = Fixture()
    first = fixture.deploy.execute(request("c1"))
    fixture.deploy.execute(request("c2", edited("Second.\n")))
    assert fixture.journal.entries[1].payload["replaced"] == {
        "repository": REPOSITORY,
        "commit": "c1",
        "content_hash": first.content_hash,
    }


def test_putting_a_commit_back_in_force_is_a_fact_of_its_own() -> None:
    fixture = Fixture()
    fixture.deploy.execute(request("c1"))
    fixture.clock.at = NOW.replace(hour=13)
    fixture.deploy.execute(request("c2", edited("Second.\n")))
    fixture.clock.at = NOW.replace(hour=14)
    again = fixture.deploy.execute(request("c1"))
    assert again.outcome == "deployed"
    assert [e.payload["commit"] for e in fixture.journal.entries] == [
        "c1",
        "c2",
        "c1",
    ]
    assert len({e.event_id for e in fixture.journal.entries}) == 3


def test_a_check_stores_nothing_and_records_nothing() -> None:
    fixture = Fixture()
    answered = fixture.deploy.execute(request(check_only=True))
    assert answered.outcome == "checked"
    assert answered.in_force is None
    assert fixture.deployments.in_force() is None
    assert fixture.journal.entries == []


def test_a_check_says_which_deployment_is_in_force() -> None:
    fixture = Fixture()
    fixture.deploy.execute(request("c1"))
    answered = fixture.deploy.execute(
        request("c2", edited("Second.\n"), check_only=True)
    )
    assert answered.in_force is not None and answered.in_force.commit == "c1"
    assert fixture.deployments.held(REPOSITORY, "c2") is None


def test_files_that_do_not_parse_are_refused_and_nothing_changes() -> None:
    fixture = Fixture()
    fixture.deploy.execute(request("c1"))
    broken = READ | {"prose/policies/P-01-example.md": "broken\n"}
    with pytest.raises(PolicyDeploymentError, match="no --- line"):
        fixture.deploy.execute(request("c2", broken))
    in_force = fixture.deployments.in_force()
    assert in_force is not None and in_force.commit == "c1"
    assert len(fixture.journal.entries) == 1


def test_a_commit_held_with_other_content_is_refused() -> None:
    fixture = Fixture()
    fixture.deploy.execute(request("c1"))
    with pytest.raises(PolicyDeploymentConflictError):
        fixture.deploy.execute(request("c1", edited("Changed.\n")))
    assert len(fixture.journal.entries) == 1
