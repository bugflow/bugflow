"""Which repositories a server watches: each that any gnome judges, by
its setting (ADR 008).

The poller, the worker's schedules and the webhooks read it here, at
each use, so a gnome set on a repository is watched without a
redeploy.
"""

from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.review.domain.services.gnome_settings import (
    GnomeSettingsService,
)


def watched(settings: GnomeSettingsService) -> tuple[WatchedRepository, ...]:
    """Each repository a gnome judges, by forge and name, once."""
    found: dict[tuple[str, str], WatchedRepository] = {}
    for one in settings.settings():
        if not one.judges:
            continue
        owner, _, repo = one.repo.partition("/")
        found.setdefault(
            (one.forge, one.repo),
            WatchedRepository(
                forge="forgejo" if one.forge == "forgejo" else "github",
                owner=owner,
                repo=repo,
            ),
        )
    return tuple(found[key] for key in sorted(found))


def watched_names(settings: GnomeSettingsService) -> tuple[str, ...]:
    """The same, each as ``owner/repo`` or ``forgejo:owner/repo``."""
    return tuple(str(one) for one in watched(settings))
