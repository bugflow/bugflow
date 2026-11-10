"""Deploying keeps what one tenant holds from another (ADR 011): a
reviewer's id is one tenant's on a server, a layer's name has one
cadence, and a setting of another tenant's gnome is that tenant's to
keep."""

import pytest

from bugflow.apps.shared.deploying import Deploying, deploying_with
from bugflow.method.domain.errors import PolicyDeploymentError
from bugflow.method.dtos.deploy_policies import (
    DeployPoliciesRequest,
    PolicyFile,
)
from bugflow.method.infrastructure.in_memory_policy_deployments import (
    InMemoryPolicyDeployments,
)
from bugflow.method.tests.policy_files import READ, TOPOLOGY
from bugflow.review.domain.models.gnome_setting import GnomeSetting
from bugflow.review.infrastructure.in_memory_gnome_settings import (
    InMemoryGnomeSettings,
)
from bugflow.review.infrastructure.in_memory_layer_boundaries import (
    InMemoryLayerBoundaries,
)
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal

OURS = "example-org/pull-request-policies"
THEIRS = "example-org/site-policies"
#: The same files, for a reviewer named site.
SITE = {
    path.replace("prose", "site"): text.replace("prose", "site")
    for path, text in READ.items()
}
STRICT = READ | {
    "profiles.toml": '[profile.prose.strict]\npolicies = ["P-01"]\n'
}


class Fixture:
    def __init__(self, *settings: GnomeSetting) -> None:
        self.journal = InMemoryJournal()
        self.deployments = InMemoryPolicyDeployments(journal=self.journal)
        self.settings = InMemoryGnomeSettings(*settings)
        self.deploying: Deploying = deploying_with(
            self.deployments, (), self.settings, InMemoryLayerBoundaries()
        )

    def deploy(
        self,
        tenant: str,
        files: dict[str, str],
        commit: str = "c1",
        check_only: bool = False,
    ) -> str:
        return self.deploying.deploy.execute(
            DeployPoliciesRequest(
                repository=OURS if tenant == "default" else THEIRS,
                commit=commit,
                files=tuple(
                    PolicyFile(path=path, text=text)
                    for path, text in files.items()
                ),
                check_only=check_only,
                sent_by="a test",
                tenant=tenant,
            )
        ).outcome


@pytest.mark.parametrize("check_only", [False, True])
def test_a_reviewer_another_tenant_holds_is_refused(check_only: bool) -> None:
    fixture = Fixture()
    fixture.deploy("default", READ)
    with pytest.raises(PolicyDeploymentError, match="prose is default's"):
        fixture.deploy("business-development", READ, check_only=check_only)
    assert fixture.deployments.in_force("business-development") is None


def test_a_reviewer_of_its_own_is_taken() -> None:
    fixture = Fixture()
    fixture.deploy("default", READ)
    assert fixture.deploy("business-development", SITE) == "deployed"
    assert fixture.deployments.tenants() == ("business-development", "default")


def test_a_layer_another_tenant_runs_at_another_cadence_is_refused() -> None:
    fixture = Fixture()
    fixture.deploy("default", READ)
    weekly = SITE | {
        "pace-layers.toml": TOPOLOGY.replace(
            'cadence = "event"', 'cadence = "weekly"'
        )
    }
    with pytest.raises(
        PolicyDeploymentError,
        match="pull-request runs at the event cadence for default and at "
        "the weekly cadence here",
    ):
        fixture.deploy("business-development", weekly)


def test_a_setting_of_another_tenants_gnome_does_not_hold_a_deployment() -> (
    None
):
    """The check that a deployment drops no profile a setting names is
    about this tenant's gnomes; another tenant's setting is kept by
    that tenant's deployment."""
    fixture = Fixture(
        GnomeSetting(
            forge="github",
            repo="example-org/widgets",
            gnome="prose",
            behaviour="observe",
            profile="strict",
        )
    )
    fixture.deploy("default", STRICT)
    assert fixture.deploy("business-development", SITE) == "deployed"
    with pytest.raises(PolicyDeploymentError, match="sets prose to strict"):
        fixture.deploy("default", READ, commit="c2")


def test_the_one_tenants_own_earlier_deployment_is_no_other_tenant() -> None:
    fixture = Fixture()
    fixture.deploy("default", READ)
    assert fixture.deploy("default", STRICT, commit="c2") == "deployed"
