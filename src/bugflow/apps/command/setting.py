"""Setting what each gnome does on each repository (ADR 008): ``bugflow
set`` and ``settings``.

``set`` writes one setting through ``SetGnomeUseCase``, which records it
in the journal. ``settings`` prints what is held. A setting is one
tenant's (ADR 012): ``--tenant`` names it, or it is the one tenant that
holds the gnome, and each line names a gnome by its qualified name.

A refusal is written to the error stream and returns 2.
"""

import getpass
import sys
import uuid
from collections.abc import Collection
from typing import TextIO

from bugflow.apps.command.declaring import Console, _split
from bugflow.apps.shared.journals import stamped_journal
from bugflow.apps.shared.policies import tenants_in_force
from bugflow.apps.shared.setting_tenant import tenant_of_setting
from bugflow.method.infrastructure.sqlalchemy_policy_deployments import (
    SqlAlchemyPolicyDeployments,
)
from bugflow.review.domain.models.gnome_setting import (
    BEHAVIOURS,
    GnomeSetting,
    qualified,
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
        f"{setting.forge}:{setting.repo} {setting.qualified} "
        f"{setting.behaviour} {setting.profile}, set by {setting.set_by} at "
        f"{when}"
    )


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
    tenant: str | None = None,
) -> int:
    """Set what a gnome does on a repository, and print what is held for
    the repository afterwards.

    ``profile`` None keeps the gnome's profile there, or ``default``
    where it had none. ``set_by`` None records the operating system's
    user, as ``host:NAME``. ``tenant`` None is the one tenant that
    holds the gnome; where two do, the setting is refused.
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
    reviewers = tenants_in_force(
        SqlAlchemyPolicyDeployments(database_url), checks
    )
    if not reviewers.by_tenant:
        return console.refuse(
            "no policy deployment is in force, so no gnome can be set"
        )
    settings = SqlAlchemyGnomeSettings(database_url)
    held = settings.settings_of(forge, repo)
    try:
        whose = tenant_of_setting(reviewers, gnome, held, tenant)
    except ValueError as exc:
        return console.refuse(str(exc))
    kept = next(
        (one for one in held if (one.gnome, one.tenant) == (gnome, whose)),
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
                tenant=whose,
                set_by=set_by or f"host:{getpass.getuser()}",
                profiles=reviewers.profiles_of(whose),
            )
        )
    except (UnknownGnomeError, ValueError) as exc:
        return console.refuse(str(exc))
    if not answered.changed:
        console.say(
            f"{forge}:{repo} {qualified(answered.tenant, gnome)} was "
            "already so; nothing recorded"
        )
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
