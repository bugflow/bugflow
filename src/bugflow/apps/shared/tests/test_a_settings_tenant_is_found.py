"""Whose a setting is when the operator names no tenant (ADR 012)."""

from dataclasses import replace

import pytest

from bugflow.apps.shared.policies import tenants_in_force
from bugflow.apps.shared.setting_tenant import tenant_of_setting
from bugflow.apps.shared.tests.test_the_reviewers_in_force import deployment
from bugflow.method.domain.models.policy_deployment import DEFAULT_TENANT
from bugflow.method.infrastructure.in_memory_policy_deployments import (
    InMemoryPolicyDeployments,
)
from bugflow.method.tests.policy_files import READ
from bugflow.review.domain.models.gnome_setting import (
    DEFAULT_TENANT as THE_REVIEW_CONTEXTS_DEFAULT,
)
from bugflow.review.domain.models.gnome_setting import GnomeSetting

THEIRS = "business-development"
SITE = {
    path.replace("prose", "site"): text.replace("prose", "site")
    for path, text in READ.items()
}


def in_force(*theirs: dict[str, str]) -> InMemoryPolicyDeployments:
    deployments = InMemoryPolicyDeployments()
    deployments.deploy(deployment())
    for files in theirs:
        deployments.deploy(replace(deployment(files, "c2"), tenant=THEIRS))
    return deployments


def kept(gnome: str, tenant: str) -> GnomeSetting:
    return GnomeSetting(
        forge="github", repo="o/w", gnome=gnome, behaviour="off", tenant=tenant
    )


def test_the_two_contexts_name_the_same_default_tenant() -> None:
    assert DEFAULT_TENANT == THE_REVIEW_CONTEXTS_DEFAULT


def test_a_gnome_one_tenant_holds_is_that_tenants() -> None:
    reviewers = tenants_in_force(in_force(SITE), ())
    assert tenant_of_setting(reviewers, "prose", ()) == "default"
    assert tenant_of_setting(reviewers, "site", ()) == THEIRS


def test_a_gnome_two_tenants_hold_needs_its_tenant_named() -> None:
    reviewers = tenants_in_force(in_force(READ), ())
    with pytest.raises(
        ValueError, match="held by business-development and default"
    ):
        tenant_of_setting(reviewers, "prose", ())
    assert tenant_of_setting(reviewers, "prose", (), THEIRS) == THEIRS
    with pytest.raises(ValueError, match="no tenant's name"):
        tenant_of_setting(reviewers, "prose", (), "Business Development")


def test_a_gnome_no_deployment_holds_is_whose_setting_the_repository_has() -> (
    None
):
    """So that a gnome a tenant's deployment dropped is switched off as
    that tenant's."""
    reviewers = tenants_in_force(in_force(), ())
    assert (
        tenant_of_setting(reviewers, "gone", (kept("gone", THEIRS),)) == THEIRS
    )
    with pytest.raises(ValueError, match="name the tenant"):
        tenant_of_setting(
            reviewers, "gone", (kept("gone", THEIRS), kept("gone", "default"))
        )
    assert tenant_of_setting(reviewers, "gone", ()) == "default"
