"""The settings of one tenant's gnomes and no other's (ADR 012).

A tenant's worker reads its own tenant's settings. Another tenant's
gnome on the same repository, of the same id or another, is that
tenant's to judge, publish and schedule, so this worker does not see it
set.
"""

from collections.abc import Iterable

from bugflow.review.domain.models.gnome_setting import GnomeSetting
from bugflow.review.domain.services.gnome_settings import (
    GnomeSettingsService,
)


class TenantSettings:
    """Implements ``GnomeSettingsService`` over another, answering only
    the tenant's settings, and refusing to save another tenant's."""

    def __init__(self, settings: GnomeSettingsService, tenant: str) -> None:
        self._settings = settings
        self._tenant = tenant

    def _ours(self, held: Iterable[GnomeSetting]) -> tuple[GnomeSetting, ...]:
        return tuple(one for one in held if one.tenant == self._tenant)

    def settings_of(self, forge: str, repo: str) -> tuple[GnomeSetting, ...]:
        return self._ours(self._settings.settings_of(forge, repo))

    def settings(self) -> tuple[GnomeSetting, ...]:
        return self._ours(self._settings.settings())

    def save(self, setting: GnomeSetting) -> None:
        if setting.tenant != self._tenant:
            raise ValueError(
                f"the setting of {setting.qualified} on {setting.forge}:"
                f"{setting.repo} is {setting.tenant}'s, not {self._tenant}'s "
                "to save"
            )
        self._settings.save(setting)
