"""Setting what each gnome does on each repository (ADR 008): ``bugflow
set`` and ``settings``.

``set`` writes one setting through ``SetGnomeUseCase``, which records it
in the journal. ``settings`` prints what is held.

A refusal is written to the error stream and returns 2.
"""

import getpass
import sys
import uuid
from collections.abc import Collection
from typing import TextIO

from bugflow.apps.command.declaring import Console, _split
from bugflow.apps.shared.journals import stamped_journal
from bugflow.apps.shared.policies import ReviewersInForce, reviewers_in_force
from bugflow.method.infrastructure.sqlalchemy_policy_deployments import (
    SqlAlchemyPolicyDeployments,
)
from bugflow.review.domain.models.gnome_setting import (
    BEHAVIOURS,
    GnomeSetting,
)
from bugflow.review.domain.services.gnome_settings import (
    GnomeSettingsService,
)
from bugflow.review.dtos.set_gnome import SetGnomeRequest
from bugflow.review.infrastructure.sqlalchemy_gnome_settings import (
    SqlAlchemyGnomeSettings,
)
from bugflow.review.usecases.set_gnome import (
    SetGnomeUseCase,
    UnknownGnomeError,
)
from bugflow.shared.infrastructure.system_clock import SystemClock


def _console(out: TextIO | None, err: TextIO | None) -> Console:
    return Console(out=out or sys.stdout, err=err or sys.stderr)


def _line(setting: GnomeSetting) -> str:
    when = setting.set_at.isoformat() if setting.set_at else "an unknown time"
    return (
        f"{setting.forge}:{setting.repo} {setting.gnome} {setting.behaviour} "
        f"{setting.profile}, set by {setting.set_by} at {when}"
    )


def _profiles(reviewers: ReviewersInForce) -> dict[str, tuple[str, ...]]:
    """Each gnome's profile names, by agent id."""
    return {
        agent_id: tuple(sorted(named))
        for agent_id, named in reviewers.profiles.items()
    }


def _setter(
    database_url: str,
    settings: GnomeSettingsService,
    build: str | None,
) -> SetGnomeUseCase:
    return SetGnomeUseCase(
        settings,
        stamped_journal(database_url, build),
        SystemClock(),
        uuid.uuid4().hex,
    )


def run_set(
    database_url: str,
    repository: str,
    gnome: str,
    behaviour: str,
    profile: str | None,
    checks: Collection[str],
    build: str | None = None,
    set_by: str | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Set what a gnome does on a repository, and print what is held for
    the repository afterwards.

    ``profile`` None keeps the gnome's profile there, or ``default``
    where it had none. ``set_by`` None records the operating system's
    user, as ``host:NAME``.
    """
    console = _console(out, err)
    try:
        forge, repo = _split(repository)
    except ValueError as exc:
        return console.refuse(str(exc))
    if behaviour not in BEHAVIOURS:
        return console.refuse(
            f"{behaviour!r} is no behaviour; name one of "
            f"{', '.join(BEHAVIOURS)}"
        )
    reviewers = reviewers_in_force(
        SqlAlchemyPolicyDeployments(database_url), checks
    )
    if reviewers is None:
        return console.refuse(
            "no policy deployment is in force, so no gnome can be set"
        )
    settings = SqlAlchemyGnomeSettings(database_url)
    kept = next(
        (
            one
            for one in settings.settings_of(forge, repo)
            if one.gnome == gnome
        ),
        None,
    )
    try:
        answered = _setter(database_url, settings, build).execute(
            SetGnomeRequest(
                forge=forge,
                repo=repo,
                gnome=gnome,
                behaviour=behaviour,
                profile=profile or (kept.profile if kept else "default"),
                set_by=set_by or f"host:{getpass.getuser()}",
                profiles=_profiles(reviewers),
            )
        )
    except (UnknownGnomeError, ValueError) as exc:
        return console.refuse(str(exc))
    if not answered.changed:
        console.say(f"{forge}:{repo} {gnome} was already so; nothing recorded")
    for one in settings.settings_of(forge, repo):
        console.say(_line(one))
    return 0


def run_settings(
    database_url: str,
    repository: str = "",
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Print every setting, or the repository's. A gnome a repository
    has no setting for is ``off`` there and is not printed."""
    console = _console(out, err)
    settings = SqlAlchemyGnomeSettings(database_url)
    if repository:
        try:
            forge, repo = _split(repository)
        except ValueError as exc:
            return console.refuse(str(exc))
        held = settings.settings_of(forge, repo)
    else:
        held = settings.settings()
    for one in held:
        console.say(_line(one))
    if not held:
        console.say("no gnome is set on any repository named; each is off")
    return 0
