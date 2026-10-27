"""Discovering the repositories of the owners a server can reach,
composed (ADR 008).

The forge context finds what changed and keeps it. Every gnome on a
repository found archived is switched off here, through the review
context's use case, so the switch is recorded like any other. Both
``bugflow discover`` and the worker's daily run compose it here.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from bugflow.apps.shared.forges import forge_tokens
from bugflow.apps.shared.journals import stamped_journal
from bugflow.forge.domain.services.repository_listing import (
    RepositoryListingService,
)
from bugflow.forge.dtos.discover_repositories import (
    DiscoverRepositoriesRequest,
    DiscoverRepositoriesResponse,
)
from bugflow.forge.infrastructure.github import GitHubForge
from bugflow.forge.infrastructure.sqlalchemy_known_repositories import (
    SqlAlchemyKnownRepositories,
)
from bugflow.forge.usecases.discover_repositories import (
    DiscoverRepositoriesUseCase,
)
from bugflow.review.dtos.set_gnome import SetGnomeRequest
from bugflow.review.infrastructure.sqlalchemy_gnome_settings import (
    SqlAlchemyGnomeSettings,
)
from bugflow.review.usecases.set_gnome import SetGnomeUseCase
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.infrastructure.system_clock import SystemClock

#: Who discovery records as having switched a gnome off.
DISCOVERY = "bugflow discovery"

#: The setting that names the owners whose repositories are listed,
#: comma-separated. Unset, they are the owners FORGE_TOKENS_BY_OWNER
#: holds a token for.
OWNERS_VARIABLE = "DISCOVERY_OWNERS"

#: How often the worker discovers, in seconds, by
#: ``DISCOVERY_INTERVAL_SECONDS``. Zero, and it does not.
INTERVAL_VARIABLE = "DISCOVERY_INTERVAL_SECONDS"
DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60.0


@dataclass(frozen=True)
class Discovering:
    """What discovery needs, read from the environment."""

    database_url: str
    owners: tuple[str, ...]
    listing: RepositoryListingService
    build: str | None = None


def owners_from(environ: Mapping[str, str]) -> tuple[str, ...]:
    """The owners whose repositories are listed."""
    named = tuple(
        one.strip()
        for one in environ.get(OWNERS_VARIABLE, "").split(",")
        if one.strip()
    )
    if named:
        return named
    tokens = forge_tokens(environ)
    return tuple(sorted(tokens.by_owner)) if tokens else ()


def interval_from(environ: Mapping[str, str]) -> float:
    """Seconds between discoveries, or ``ValueError``."""
    raw = environ.get(INTERVAL_VARIABLE) or str(DEFAULT_INTERVAL_SECONDS)
    try:
        seconds = float(raw)
    except ValueError:
        seconds = -1.0
    if seconds < 0:
        raise ValueError(
            f"{INTERVAL_VARIABLE} is {raw!r}, not a number of seconds"
        )
    return seconds


def discovering_from(
    environ: Mapping[str, str], build: str | None = None
) -> Discovering | None:
    """What discovery needs, or None where there is no database, no
    GitHub token or no owner to list."""
    database_url = environ.get("DATABASE_URL", "")
    tokens = forge_tokens(environ)
    owners = owners_from(environ)
    if not database_url or tokens is None or not owners:
        return None
    return Discovering(
        database_url=database_url,
        owners=owners,
        listing=GitHubForge(tokens),
        build=build,
    )


def discover(
    discovering: Discovering,
    profiles: Mapping[str, tuple[str, ...]] | None = None,
) -> DiscoverRepositoriesResponse:
    """List each owner's repositories, keep what changed, and switch off
    every gnome on a repository found archived."""
    journal = stamped_journal(discovering.database_url, discovering.build)
    clock = SystemClock()
    run_id = uuid.uuid4().hex
    found = DiscoverRepositoriesUseCase(
        discovering.listing,
        SqlAlchemyKnownRepositories(discovering.database_url),
        journal,
        clock,
    ).execute(
        DiscoverRepositoriesRequest(
            owners=discovering.owners,
            correlation=Correlation(
                workflow_id="repositories/discover", run_id=run_id
            ),
        )
    )
    settings = SqlAlchemyGnomeSettings(discovering.database_url)
    switch = SetGnomeUseCase(settings, journal, clock, run_id)
    for change in found.changes:
        if change.change != "archived":
            continue
        for one in settings.settings_of(change.forge, change.name):
            if one.behaviour == "off":
                continue
            switch.execute(
                SetGnomeRequest(
                    forge=one.forge,
                    repo=one.repo,
                    gnome=one.gnome,
                    behaviour="off",
                    profile=one.profile,
                    set_by=DISCOVERY,
                    profiles=profiles or {},
                )
            )
    return found


def said(found: DiscoverRepositoriesResponse) -> list[str]:
    """What a discovery did, a line each."""
    lines = [
        f"{one.change} {one.forge}:{one.name}"
        + (f", was {one.was_name}" if one.was_name else "")
        for one in found.changes
    ]
    lines += [f"failed: {one}" for one in found.failures]
    lines.append(
        f"discovered: {len(found.changes)} changed, "
        f"{len(found.failures)} owner(s) failed"
    )
    return lines
