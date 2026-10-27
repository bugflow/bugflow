"""Deploying refuses a deployment that drops a profile a setting names
(ADR 008). The use case itself is the method context's, tested
there."""

from datetime import UTC, datetime

import pytest

from bugflow.apps.shared.deploying import (
    CHECKS_VARIABLE,
    Deploying,
    checks_from,
    deploying_with,
)
from bugflow.method.domain.errors import PolicyDeploymentError
from bugflow.method.dtos.deploy_policies import (
    DeployPoliciesRequest,
    PolicyFile,
)
from bugflow.method.infrastructure.in_memory_policy_deployments import (
    InMemoryPolicyDeployments,
)
from bugflow.method.tests.policy_files import READ
from bugflow.review.domain.models.gnome_setting import (
    Behaviour,
    GnomeSetting,
)
from bugflow.review.infrastructure.in_memory_gnome_settings import (
    InMemoryGnomeSettings,
)
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal

REPOSITORY = "example-org/pull-request-policies"
STRICT = READ | {
    "profiles.toml": '[profile.prose.strict]\npolicies = ["P-01"]\n'
}


class Fixture:
    def __init__(self, *settings: GnomeSetting) -> None:
        self.deployments = InMemoryPolicyDeployments()
        self.journal = InMemoryJournal()
        self.settings = InMemoryGnomeSettings(*settings)
        self.deploying: Deploying = deploying_with(
            self.deployments, self.journal, (), self.settings
        )

    def deploy(
        self,
        commit: str = "c1",
        files: dict[str, str] | None = None,
        check_only: bool = False,
    ) -> str:
        return self.deploying.deploy.execute(
            DeployPoliciesRequest(
                repository=REPOSITORY,
                commit=commit,
                files=tuple(
                    PolicyFile(path=path, text=text)
                    for path, text in (
                        READ if files is None else files
                    ).items()
                ),
                check_only=check_only,
                sent_by="a test",
            )
        ).outcome


def prose(behaviour: Behaviour, profile: str = "strict") -> GnomeSetting:
    return GnomeSetting(
        forge="github",
        repo="example-org/widgets",
        gnome="prose",
        behaviour=behaviour,
        profile=profile,
    )


@pytest.mark.parametrize("check_only", [False, True])
def test_a_deployment_that_drops_a_profile_in_use_is_refused(
    check_only: bool,
) -> None:
    """A pipeline's check on a pull request refuses it too, so the pull
    request that would drop it says so before it is merged."""
    fixture = Fixture(prose("observe"))
    fixture.deploy(files=STRICT)

    with pytest.raises(
        PolicyDeploymentError,
        match="github:example-org/widgets sets prose to strict",
    ):
        fixture.deploy("c2", check_only=check_only)


def test_a_profile_a_gnome_set_off_names_is_kept_too() -> None:
    """Set on again with no profile named, the gnome keeps the one it
    has, so that profile must still be there."""
    fixture = Fixture(prose("off"))
    fixture.deploy(files=STRICT)
    with pytest.raises(PolicyDeploymentError, match="sets prose to strict"):
        fixture.deploy("c2")


def test_the_default_profile_is_never_dropped() -> None:
    fixture = Fixture(prose("gate", "default"))
    assert fixture.deploy() == "deployed"


def test_the_fact_is_recorded_at_the_time_of_the_clock() -> None:
    fixture = Fixture()
    before = datetime.now(UTC)
    fixture.deploy()
    (fact,) = fixture.journal.entries
    assert fact.occurred_at >= before
    assert fact.payload["sent_by"] == "a test"


def test_the_checks_are_read_from_the_environment() -> None:
    assert checks_from({}) == ("em-dash",)
    assert checks_from({CHECKS_VARIABLE: ""}) == ()
    assert checks_from({CHECKS_VARIABLE: "em-dash, other ,"}) == (
        "em-dash",
        "other",
    )
