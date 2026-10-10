"""The reviewers a program runs with come from the deployment in force,
parsed with the checks this server has."""

import pytest

from bugflow.apps.shared.policies import reviewers_in_force
from bugflow.method.domain.errors import (
    PolicyDeploymentError,
    ReviewAgentError,
)
from bugflow.method.domain.models.policy_deployment import (
    DeployedFile,
    PolicyDeployment,
)
from bugflow.method.infrastructure.in_memory_policy_deployments import (
    InMemoryPolicyDeployments,
)
from bugflow.method.tests.policy_files import DOCTRINE, MANIFEST, READ

REPOSITORY = "example-org/pull-request-policies"


def deployment(
    files: dict[str, str] | None = None, commit: str = "c1"
) -> PolicyDeployment:
    return PolicyDeployment(
        repository=REPOSITORY,
        commit=commit,
        files=tuple(
            DeployedFile(path=path, text=text)
            for path, text in (READ if files is None else files).items()
        ),
    )


def in_force(files: dict[str, str] | None = None) -> InMemoryPolicyDeployments:
    deployments = InMemoryPolicyDeployments()
    deployments.deploy(deployment(files))
    return deployments


def test_a_server_never_sent_a_deployment_has_no_reviewers() -> None:
    assert reviewers_in_force(InMemoryPolicyDeployments(), ()) is None


def test_the_reviewers_are_those_of_the_deployment_in_force() -> None:
    reviewers = reviewers_in_force(in_force(), ())
    assert reviewers is not None
    assert set(reviewers.agents) == {"prose"}
    assert set(reviewers.policies["prose"]) == {"P-01"}
    assert "pull-request" in reviewers.layers
    assert reviewers.doctrine["prose"].text == DOCTRINE
    assert reviewers.doctrine_of("prose").load().text == DOCTRINE
    assert (
        reviewers.deployed_from.repository,
        reviewers.deployed_from.commit,
    ) == (REPOSITORY, "c1")
    assert reviewers.deployed_from.content_hash == deployment().content_hash


def test_a_reviewer_with_no_doctrine_files_cites_an_empty_one() -> None:
    without = {p: t for p, t in READ.items() if "doctrine" not in p}
    reviewers = reviewers_in_force(in_force(without), ())
    assert reviewers is not None
    assert reviewers.doctrine == {}
    assert reviewers.doctrine_of("prose").load().text == ""


def test_names_narrow_the_reviewers_to_those_named() -> None:
    reviewers = reviewers_in_force(in_force(), (), names=("prose",))
    assert reviewers is not None
    assert set(reviewers.agents) == {"prose"}
    with pytest.raises(ReviewAgentError, match="not installed: other"):
        reviewers_in_force(in_force(), (), names=("other",))


def test_a_manifest_naming_a_check_the_server_lacks_is_refused() -> None:
    checked = READ | {
        "prose/reviewer.md": MANIFEST.replace(
            "policies: P-01\n", "policies: P-01\nchecks: em-dash P-01 EX-1\n"
        )
    }
    with pytest.raises(PolicyDeploymentError, match="em-dash"):
        reviewers_in_force(in_force(checked), ())
    reviewers = reviewers_in_force(in_force(checked), ("em-dash",))
    assert reviewers is not None
    assert reviewers.agents["prose"].checks[0].check == "em-dash"
