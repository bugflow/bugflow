"""The interface for reading and writing what each gnome does on each
repository (ADR 008)."""

from typing import Protocol

from bugflow.review.domain.models.gnome_setting import GnomeSetting


class GnomeSettingsService(Protocol):
    def settings_of(self, forge: str, repo: str) -> tuple[GnomeSetting, ...]:
        """Return the repository's settings, by gnome. A gnome with none
        is ``off`` there."""
        ...

    def settings(self) -> tuple[GnomeSetting, ...]:
        """Return every setting, by forge, repository and gnome."""
        ...

    def save(self, setting: GnomeSetting) -> None:
        """Replace the repository's setting for that gnome."""
        ...
