"""The settings of some gnomes and no others, which a tenant's worker
reads (ADR 011)."""

from bugflow.review.domain.models.gnome_setting import GnomeSetting
from bugflow.review.infrastructure.gnomes_of import GnomesOf
from bugflow.review.infrastructure.in_memory_gnome_settings import (
    InMemoryGnomeSettings,
)


def setting(repo: str, gnome: str) -> GnomeSetting:
    return GnomeSetting(
        forge="github", repo=repo, gnome=gnome, behaviour="observe"
    )


def test_only_the_gnomes_named_are_seen_set() -> None:
    everything = InMemoryGnomeSettings(
        setting("o/widgets", "prose"),
        setting("o/widgets", "site"),
        setting("o/gadgets", "site"),
    )
    ours = GnomesOf(everything, {"prose"})
    assert [one.gnome for one in ours.settings_of("github", "o/widgets")] == [
        "prose"
    ]
    assert ours.settings_of("github", "o/gadgets") == ()
    assert [(one.repo, one.gnome) for one in ours.settings()] == [
        ("o/widgets", "prose")
    ]


def test_a_setting_saved_through_it_reaches_the_settings() -> None:
    everything = InMemoryGnomeSettings()
    GnomesOf(everything, {"prose"}).save(setting("o/widgets", "prose"))
    assert len(everything.settings()) == 1
