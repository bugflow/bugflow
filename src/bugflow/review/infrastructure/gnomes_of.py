"""The settings of some gnomes and no others (ADR 011).

A tenant's worker reads the settings of the gnomes its own deployment
holds. Another tenant's gnome on the same repository is that tenant's
to judge, publish and schedule, so this worker does not see it set.
"""

from collections.abc import Iterable

from bugflow.review.domain.models.gnome_setting import GnomeSetting
from bugflow.review.domain.services.gnome_settings import (
    GnomeSettingsService,
)


class GnomesOf:
    """Implements ``GnomeSettingsService`` over another, answering only
    the settings of the gnomes named. A setting is saved through it
    unchanged."""

    def __init__(
        self, settings: GnomeSettingsService, gnomes: Iterable[str]
    ) -> None:
        self._settings = settings
        self._gnomes = frozenset(gnomes)

    def _ours(self, held: Iterable[GnomeSetting]) -> tuple[GnomeSetting, ...]:
        return tuple(one for one in held if one.gnome in self._gnomes)

    def settings_of(self, forge: str, repo: str) -> tuple[GnomeSetting, ...]:
        return self._ours(self._settings.settings_of(forge, repo))

    def settings(self) -> tuple[GnomeSetting, ...]:
        return self._ours(self._settings.settings())

    def save(self, setting: GnomeSetting) -> None:
        self._settings.save(setting)
