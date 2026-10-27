"""Tests of what a repository is reviewed for and what reaches its
forge, read from each gnome's setting on it (ADR 008)."""

from bugflow.review.domain.models.gnome_setting import (
    Behaviour,
    GnomeSetting,
)
from bugflow.review.infrastructure.in_memory_gnome_settings import (
    InMemoryGnomeSettings,
)
from bugflow.review.infrastructure.settled_review import (
    SettledEnforcement,
    SettledPolicies,
)

PROFILES: dict[str, dict[str, tuple[str, ...]]] = {
    "pr-gnome": {"default": ("CM-01", "ED-01"), "strict": ("CM-01",)},
    "repo-gnome": {"default": ("CN-02",)},
}


def on_widgets(*set_to: tuple[str, Behaviour, str]) -> InMemoryGnomeSettings:
    return InMemoryGnomeSettings(
        *(
            GnomeSetting(
                forge="github",
                repo="o/widgets",
                gnome=gnome,
                behaviour=behaviour,
                profile=profile,
            )
            for gnome, behaviour, profile in set_to
        )
    )


def test_a_repository_is_judged_on_the_profile_of_each_gnome_judging() -> None:
    settings = on_widgets(
        ("pr-gnome", "advise", "strict"), ("repo-gnome", "off", "default")
    )
    judged = SettledPolicies(settings, PROFILES)
    assert judged.judged("github", "o/widgets") == {"CM-01"}
    assert judged.judged("github", "o/other") == frozenset()


def test_a_profile_the_deployment_no_longer_holds_judges_nothing() -> None:
    settings = on_widgets(("pr-gnome", "observe", "lenient"))
    assert (
        SettledPolicies(settings, PROFILES).judged("github", "o/widgets")
        == frozenset()
    )


def test_each_gnome_publishes_and_gates_as_it_is_set() -> None:
    settings = on_widgets(
        ("pr-gnome", "gate", "default"), ("repo-gnome", "observe", "default")
    )
    held = SettledEnforcement(settings).enforcement_for("github", "o/widgets")
    assert held.judging == {"pr-gnome", "repo-gnome"}
    assert held.publishing == {"pr-gnome"}
    assert held.gating == {"pr-gnome"}
    assert held.deciding == {"pr-gnome"}


def test_with_no_gnome_at_gate_the_gnomes_advising_decide_the_label() -> None:
    settings = on_widgets(
        ("pr-gnome", "advise", "default"), ("repo-gnome", "observe", "default")
    )
    held = SettledEnforcement(settings).enforcement_for("github", "o/widgets")
    assert held.deciding == {"pr-gnome"}
    assert not held.gating


def test_with_every_gnome_observing_each_decides_the_label_kept() -> None:
    settings = on_widgets(
        ("pr-gnome", "observe", "default"),
        ("repo-gnome", "observe", "default"),
    )
    held = SettledEnforcement(settings).enforcement_for("github", "o/widgets")
    assert held.deciding == {"pr-gnome", "repo-gnome"}
    assert not held.publishes


def test_only_the_gnomes_that_govern_decide_the_label() -> None:
    settings = on_widgets(
        ("pr-gnome", "advise", "default"), ("security", "advise", "default")
    )
    held = SettledEnforcement(settings, may_decide=["pr-gnome"])
    assert held.enforcement_for("github", "o/widgets").deciding == {"pr-gnome"}
