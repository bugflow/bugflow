"""What a repository is reviewed for and what reaches its forge, read
from each gnome's setting on it (ADR 008).

``SettledPolicies`` answers which policies are judged: those of each
gnome's profile, for every gnome at ``observe`` or above.
``SettledProcesses`` answers which processes run: one that names a
reviewer, where that reviewer's gnome judges, and any other on a
repository any gnome judges. ``SettledEnforcement`` answers which gnomes
publish and gate, with the repository's withheld share.

Each reads the settings when it is asked, so a setting changes a review
without a restart. The profiles are the deployment in force's, which a
worker reads once and restarts to read again.
"""

from collections.abc import Collection, Mapping

from bugflow.review.domain.models.enforcement import Enforcement
from bugflow.review.domain.services.gnome_settings import (
    GnomeSettingsService,
)
from bugflow.review.domain.services.withholding import WithholdingService


class SettledPolicies:
    def __init__(
        self,
        settings: GnomeSettingsService,
        profiles: Mapping[str, Mapping[str, tuple[str, ...]]],
    ) -> None:
        self._settings = settings
        self._profiles = profiles

    def judged(self, forge: str, repo: str) -> frozenset[str]:
        # A setting naming a gnome or a profile the deployment in force
        # does not hold judges nothing: a deployment that drops one in
        # use is refused, so this is a setting older than the worker's
        # deployment, and quiet is safer than a guess.
        return frozenset(
            policy_id
            for one in self._settings.settings_of(forge, repo)
            if one.judges
            for policy_id in self._profiles.get(one.gnome, {}).get(
                one.profile, ()
            )
        )


class SettledProcesses:
    def __init__(
        self,
        settings: GnomeSettingsService,
        processes: Mapping[str, str | None],
    ) -> None:
        """``processes`` gives each process's reviewer, by process name,
        or None for a process that names none."""
        self._settings = settings
        self._processes = dict(processes)

    def dispatched(self, forge: str, repo: str) -> frozenset[str]:
        judging = {
            one.gnome
            for one in self._settings.settings_of(forge, repo)
            if one.judges
        }
        if not judging:
            return frozenset()
        return frozenset(
            name
            for name, reviewer in self._processes.items()
            if reviewer is None or reviewer in judging
        )


class SettledEnforcement:
    def __init__(
        self,
        settings: GnomeSettingsService,
        withholding: WithholdingService | None = None,
        may_decide: Collection[str] | None = None,
    ) -> None:
        self._settings = settings
        # None where the deployment holds no share, and then nothing is
        # withheld anywhere, which is what a share of 0 says too.
        self._withholding = withholding
        # The gnomes whose manifests say they govern, or None for every
        # gnome.
        self._may_decide = (
            None if may_decide is None else frozenset(may_decide)
        )

    def enforcement_for(self, forge: str, repo: str) -> Enforcement:
        held = self._settings.settings_of(forge, repo)
        return Enforcement(
            judging=frozenset(one.gnome for one in held if one.judges),
            publishing=frozenset(one.gnome for one in held if one.publishes),
            gating=frozenset(one.gnome for one in held if one.gates),
            withholds=self._withholding.share_for(forge, repo)
            if self._withholding
            else 0.0,
            may_decide=self._may_decide,
        )
