"""Setting what each gnome does on each repository (ADR 008): ``bugflow
set``, ``settings`` and ``settle``.

``set`` writes one setting through ``SetGnomeUseCase``, which records it
in the journal. ``settings`` prints what is held. ``settle`` makes the
settings once from what a server declared before ADR 008: the policies
each repository was judged on, its enforcement profile and which
reviewers governed its label. It refuses, and writes nothing, where a
repository's declared policies for a gnome are no profile of the
deployment in force, so that no setting is made by guess.

A refusal is written to the error stream and returns 2.
"""

import getpass
import sys
import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import TextIO, cast

from bugflow.apps.command.declaring import Console, _split
from bugflow.apps.shared.journals import stamped_journal
from bugflow.apps.shared.policies import ReviewersInForce, reviewers_in_force
from bugflow.apps.worker.reviewers import governing_by_default
from bugflow.method.infrastructure.sqlalchemy_policy_deployments import (
    SqlAlchemyPolicyDeployments,
)
from bugflow.review.domain.models.gnome_setting import (
    BEHAVIOURS,
    Behaviour,
    GnomeSetting,
)
from bugflow.review.domain.services.gnome_settings import (
    GnomeSettingsService,
)
from bugflow.review.dtos.set_gnome import SetGnomeRequest
from bugflow.review.infrastructure.sqlalchemy_enforcement import (
    SqlAlchemyEnforcement,
)
from bugflow.review.infrastructure.sqlalchemy_gnome_settings import (
    SqlAlchemyGnomeSettings,
)
from bugflow.review.infrastructure.sqlalchemy_governance import (
    SqlAlchemyGovernance,
)
from bugflow.review.infrastructure.sqlalchemy_review_declaration import (
    SqlAlchemyJudgedPolicies,
)
from bugflow.review.usecases.set_gnome import (
    SetGnomeUseCase,
    UnknownGnomeError,
)
from bugflow.shared.infrastructure.system_clock import SystemClock

#: Who ``settle`` records as having made the settings it makes.
SETTLED_BY = "bugflow settle"


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


@dataclass(frozen=True, kw_only=True)
class Settled:
    """A setting ``settle`` makes."""

    forge: str
    repo: str
    gnome: str
    behaviour: Behaviour
    profile: str


def settled(
    reviewers: ReviewersInForce,
    judged: Mapping[tuple[str, str], frozenset[str]],
    profiles: Mapping[tuple[str, str], str],
    governing: Mapping[tuple[str, str], frozenset[str]],
) -> tuple[list[Settled], list[str]]:
    """The settings a server's declarations make, and why any cannot be
    made.

    ``judged`` is each repository's declared policies, ``profiles`` its
    enforcement profile's name and ``governing`` the reviewers that
    decided its label, each by forge and repository.

    A gnome a repository declared none of the policies of is ``off``
    there and has no setting. Otherwise it takes the profile whose
    policies are exactly those declared, ``default`` first, and the
    enforcement profile's behaviour, except that ``gate`` is ``advise``
    for a gnome that did not govern the label, whose status never
    failed.
    """
    made: list[Settled] = []
    problems: list[str] = []
    repositories = sorted(set(judged) | set(profiles))
    for forge, repo in repositories:
        declared = judged.get((forge, repo), frozenset())
        old = profiles.get((forge, repo), "observe")
        for gnome, agent in sorted(reviewers.agents.items()):
            mine = frozenset(p for p in declared if p in agent.policies)
            if not mine:
                continue
            named = reviewers.profiles.get(gnome, {})
            matching = sorted(
                (
                    name
                    for name, held in named.items()
                    if frozenset(held) == mine
                ),
                key=lambda name: (name != "default", name),
            )
            if not matching:
                problems.append(
                    f"{forge}:{repo} declares {', '.join(sorted(mine))} of "
                    f"{gnome}, which is no profile of it; deploy a profile "
                    "of those policies and settle again"
                )
                continue
            behaviour = cast(Behaviour, old)
            if old == "gate" and gnome not in governing.get(
                (forge, repo), frozenset()
            ):
                behaviour = "advise"
            made.append(
                Settled(
                    forge=forge,
                    repo=repo,
                    gnome=gnome,
                    behaviour=behaviour,
                    profile=matching[0],
                )
            )
    return made, problems


def run_settle(
    database_url: str,
    checks: Collection[str],
    build: str | None = None,
    check_only: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Make the settings from the server's declarations, once.

    A repository and gnome that already has a setting is left as it is,
    so running it again makes nothing new. With ``check_only`` it prints
    what it would make and writes nothing.
    """
    console = _console(out, err)
    reviewers = reviewers_in_force(
        SqlAlchemyPolicyDeployments(database_url), checks
    )
    if reviewers is None:
        return console.refuse(
            "no policy deployment is in force, so no profile is known"
        )
    judged = {
        (one.forge, one.repo): frozenset(one.policies)
        for one in SqlAlchemyJudgedPolicies(database_url).declarations()
        if one.policies
    }
    profiles = {
        key: profile.name
        for key, profile in SqlAlchemyEnforcement(database_url)
        .bindings()
        .items()
    }
    governance = SqlAlchemyGovernance(
        database_url, governing_by_default(reviewers.agents)
    )
    governing = {
        key: governance.governing_agents(*key)
        for key in set(judged) | set(profiles)
    }
    made, problems = settled(reviewers, judged, profiles, governing)
    if problems:
        for problem in problems:
            console.say(f"refused: {problem}")
        return console.refuse(
            f"{len(problems)} declaration(s) match no profile; nothing "
            "is settled"
        )
    settings = SqlAlchemyGnomeSettings(database_url)
    held = {(one.forge, one.repo, one.gnome) for one in settings.settings()}
    setter = _setter(database_url, settings, build)
    known = _profiles(reviewers)
    for one in made:
        where = f"{one.forge}:{one.repo} {one.gnome}"
        if (one.forge, one.repo, one.gnome) in held:
            console.say(f"{where} is already set; left as it is")
            continue
        if check_only:
            console.say(f"{where} would be {one.behaviour} {one.profile}")
            continue
        setter.execute(
            SetGnomeRequest(
                forge=one.forge,
                repo=one.repo,
                gnome=one.gnome,
                behaviour=one.behaviour,
                profile=one.profile,
                set_by=SETTLED_BY,
                profiles=known,
            )
        )
        console.say(f"{where} is {one.behaviour} {one.profile}")
    if not made:
        console.say("nothing is declared, so nothing is settled")
    return 0
