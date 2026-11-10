"""A delivery is handed to each tenant whose gnome judges the
repository, and a completion to the tenant whose reviewer was
dispatched (ADR 011), offered to each tenant that holds the reviewer's
id until one was waiting (ADR 012)."""

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
THEIRS = "business-development"
HOLDERS = {"prose": ("default", THEIRS), "site": (THEIRS,)}


class FakeStarter:
    def __init__(self, tenant: str, running: bool = False) -> None:
        self.tenant = tenant
        self.running = running
        #: The runs this tenant's namespace holds, which a completion
        #: of any other run finds nothing waiting for.
        self.waiting: set[str] = set()
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
        if self.waiting and correlation.run_id not in self.waiting:
            return Acknowledgement.unable("no evaluation was waiting")
        return Acknowledgement.wilco()


def setting(
    gnome: str, behaviour: Behaviour = "observe", tenant: str = "default"
) -> GnomeSetting:
    return GnomeSetting(
        forge="github",
        repo="o/widgets",
        gnome=gnome,
        behaviour=behaviour,
        tenant=tenant,
    )


def starters(
    *settings: GnomeSetting,
) -> tuple[TenantStarters, FakeStarter, FakeStarter]:
    ours, theirs = FakeStarter("default"), FakeStarter(THEIRS)
    return (
        TenantStarters(
            {"default": ours, THEIRS: theirs},
            "default",
            HOLDERS,
            InMemoryGnomeSettings(*settings),
        ),
        ours,
        theirs,
    )


def test_a_delivery_reaches_the_tenants_whose_gnomes_judge() -> None:
    fan_out, ours, theirs = starters(
        setting("prose"), setting("site", tenant=THEIRS)
    )
    started = fan_out.start(WIDGETS, "d-1")
    assert ours.started == ["d-1"] and theirs.started == ["d-1"]
    assert started.run_id == THEIRS


def test_a_delivery_reaches_one_tenant_alone_where_its_gnome_judges() -> None:
    fan_out, ours, theirs = starters(
        setting("prose", "off"), setting("site", tenant=THEIRS)
    )
    fan_out.start(WIDGETS, "d-1")
    assert ours.started == [] and theirs.started == ["d-1"]


def test_each_tenants_setting_of_one_gnome_is_read_as_its_own() -> None:
    """Two tenants hold prose (ADR 012); the one whose setting judges
    is reached."""
    fan_out, ours, theirs = starters(
        setting("prose", "off"), setting("prose", tenant=THEIRS)
    )
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
        HOLDERS,
        InMemoryGnomeSettings(setting("site", tenant=THEIRS)),
    )
    fan_out.start(WIDGETS, "d-1")
    # Nobody judging reached, so the own tenant takes it.
    assert ours.started == ["d-1"]


def test_a_close_reaches_every_tenant_and_answers_the_one_running() -> None:
    fan_out, ours, theirs = starters(setting("site", tenant=THEIRS))
    theirs.running = True
    closed = fan_out.close(WIDGETS, "d-2", merged=True)
    assert ours.closed == ["d-2"] and theirs.closed == ["d-2"]
    assert closed is not None and closed.run_id == THEIRS
    theirs.running = False
    assert fan_out.close(WIDGETS, "d-3") is None


def test_a_completion_reaches_the_tenant_whose_reviewer_it_is() -> None:
    fan_out, ours, theirs = starters()
    correlation = Correlation(workflow_id="w", run_id="r")
    fan_out.handle_completion(correlation, "site", "remote-1")
    fan_out.handle_completion(correlation, "unknown", "remote-2")
    assert theirs.completed == ["site"]
    assert ours.completed == ["unknown"]


def test_a_completion_of_a_shared_reviewer_finds_the_tenant_waiting() -> None:
    """Both tenants hold prose. The run is in the second tenant's
    namespace, so the first answers unable and the second takes it;
    nothing waiting anywhere is answered so."""
    fan_out, ours, theirs = starters()
    ours.waiting, theirs.waiting = {"r-ours"}, {"r-theirs"}
    taken = fan_out.handle_completion(
        Correlation(workflow_id="w", run_id="r-theirs"), "prose", "remote-1"
    )
    assert taken.will_comply
    assert ours.completed == ["prose"] and theirs.completed == ["prose"]
    first = fan_out.handle_completion(
        Correlation(workflow_id="w", run_id="r-ours"), "prose", "remote-2"
    )
    assert first.will_comply and theirs.completed == ["prose"]
    nobody = fan_out.handle_completion(
        Correlation(workflow_id="w", run_id="r-gone"), "prose", "remote-3"
    )
    assert nobody.will_comply is False


def test_the_own_tenant_has_a_starter() -> None:
    with pytest.raises(ValueError, match="own tenant default has no starter"):
        TenantStarters({}, "default", {}, InMemoryGnomeSettings())
