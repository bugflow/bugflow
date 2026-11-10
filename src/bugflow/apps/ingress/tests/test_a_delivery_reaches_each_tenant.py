"""A delivery is handed to each tenant whose gnome judges the
repository, and a completion to the tenant whose reviewer was
dispatched (ADR 011)."""

import pytest

from bugflow.apps.ingress.fan_out import TenantStarters
from bugflow.review.domain.models.gnome_setting import (
    Behaviour,
    GnomeSetting,
)
from bugflow.review.infrastructure.in_memory_gnome_settings import (
    InMemoryGnomeSettings,
)
from bugflow.shared.domain.values.acknowledgement import Acknowledgement
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

WIDGETS = PullRequestRef(owner="o", repo="widgets", number=6)
TENANT_OF = {"prose": "default", "site": "business-development"}


class FakeStarter:
    def __init__(self, tenant: str, running: bool = False) -> None:
        self.tenant = tenant
        self.running = running
        self.started: list[str] = []
        self.closed: list[str] = []
        self.completed: list[str] = []

    def start(self, ref: PullRequestRef, delivery_id: str) -> Correlation:
        self.started.append(delivery_id)
        return Correlation(workflow_id=f"pr/{ref.repo}", run_id=self.tenant)

    def close(
        self, ref: PullRequestRef, delivery_id: str, merged: bool = False
    ) -> Correlation | None:
        self.closed.append(delivery_id)
        if not self.running:
            return None
        return Correlation(workflow_id=f"pr/{ref.repo}", run_id=self.tenant)

    def handle_completion(
        self, correlation: Correlation, agent_id: str, remote_id: str
    ) -> Acknowledgement:
        self.completed.append(agent_id)
        return Acknowledgement.wilco()


def setting(gnome: str, behaviour: Behaviour = "observe") -> GnomeSetting:
    return GnomeSetting(
        forge="github", repo="o/widgets", gnome=gnome, behaviour=behaviour
    )


def starters(
    *settings: GnomeSetting,
) -> tuple[TenantStarters, FakeStarter, FakeStarter]:
    ours, theirs = FakeStarter("default"), FakeStarter("business-development")
    return (
        TenantStarters(
            {"default": ours, "business-development": theirs},
            "default",
            TENANT_OF,
            InMemoryGnomeSettings(*settings),
        ),
        ours,
        theirs,
    )


def test_a_delivery_reaches_the_tenants_whose_gnomes_judge() -> None:
    fan_out, ours, theirs = starters(setting("prose"), setting("site"))
    started = fan_out.start(WIDGETS, "d-1")
    assert ours.started == ["d-1"] and theirs.started == ["d-1"]
    assert started.run_id == "business-development"


def test_a_delivery_reaches_one_tenant_alone_where_its_gnome_judges() -> None:
    fan_out, ours, theirs = starters(setting("prose", "off"), setting("site"))
    fan_out.start(WIDGETS, "d-1")
    assert ours.started == [] and theirs.started == ["d-1"]


def test_a_repository_no_gnome_judges_reaches_the_own_tenant() -> None:
    """As a server with one tenant hands every delivery: journalled,
    and judged on nothing."""
    fan_out, ours, theirs = starters()
    fan_out.start(WIDGETS, "d-1")
    assert ours.started == ["d-1"] and theirs.started == []


def test_a_gnome_of_a_tenant_with_no_starter_reaches_nothing() -> None:
    ours = FakeStarter("default")
    fan_out = TenantStarters(
        {"default": ours},
        "default",
        TENANT_OF,
        InMemoryGnomeSettings(setting("site")),
    )
    fan_out.start(WIDGETS, "d-1")
    # Nobody judging reached, so the own tenant takes it.
    assert ours.started == ["d-1"]


def test_a_close_reaches_every_tenant_and_answers_the_one_running() -> None:
    fan_out, ours, theirs = starters(setting("site"))
    theirs.running = True
    closed = fan_out.close(WIDGETS, "d-2", merged=True)
    assert ours.closed == ["d-2"] and theirs.closed == ["d-2"]
    assert closed is not None and closed.run_id == "business-development"
    theirs.running = False
    assert fan_out.close(WIDGETS, "d-3") is None


def test_a_completion_reaches_the_tenant_whose_reviewer_it_is() -> None:
    fan_out, ours, theirs = starters()
    correlation = Correlation(workflow_id="w", run_id="r")
    fan_out.handle_completion(correlation, "site", "remote-1")
    fan_out.handle_completion(correlation, "unknown", "remote-2")
    assert theirs.completed == ["site"]
    assert ours.completed == ["unknown"]


def test_the_own_tenant_has_a_starter() -> None:
    with pytest.raises(ValueError, match="own tenant default has no starter"):
        TenantStarters({}, "default", {}, InMemoryGnomeSettings())
