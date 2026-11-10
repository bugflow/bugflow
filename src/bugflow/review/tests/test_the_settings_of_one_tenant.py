"""The settings of one tenant's gnomes and no other's, which a tenant's
worker reads (ADR 012)."""

import pytest

from bugflow.review.domain.models.gnome_setting import GnomeSetting
from bugflow.review.infrastructure.in_memory_gnome_settings import (
    InMemoryGnomeSettings,
)
from bugflow.review.infrastructure.tenant_settings import TenantSettings

THEIRS = "business-development"


def setting(repo: str, gnome: str, tenant: str = "default") -> GnomeSetting:
    return GnomeSetting(
        forge="github",
        repo=repo,
        gnome=gnome,
        behaviour="observe",
        tenant=tenant,
    )


def test_only_the_tenants_own_settings_are_seen() -> None:
    """Two tenants hold prose; each worker sees its own setting of it."""
    everything = InMemoryGnomeSettings(
        setting("o/widgets", "prose"),
        setting("o/widgets", "prose", THEIRS),
        setting("o/gadgets", "site", THEIRS),
    )
    ours = TenantSettings(everything, "default")
    assert [
        one.qualified for one in ours.settings_of("github", "o/widgets")
    ] == ["prose"]
    assert ours.settings_of("github", "o/gadgets") == ()
    assert [(one.repo, one.gnome) for one in ours.settings()] == [
        ("o/widgets", "prose")
    ]
    theirs = TenantSettings(everything, THEIRS)
    assert [one.qualified for one in theirs.settings()] == [
        f"{THEIRS}/site",
        f"{THEIRS}/prose",
    ]


def test_a_setting_saved_through_it_is_the_tenants_own() -> None:
    everything = InMemoryGnomeSettings()
    TenantSettings(everything, THEIRS).save(
        setting("o/widgets", "prose", THEIRS)
    )
    assert len(everything.settings()) == 1
    with pytest.raises(
        ValueError, match="is default's, not business-development's"
    ):
        TenantSettings(everything, THEIRS).save(setting("o/widgets", "prose"))
