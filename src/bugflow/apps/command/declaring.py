"""Declaring what a repository is reviewed under, and what a run may
spend: ``bugflow declare``, ``allow``, ``revoke``, ``cadence`` and
``declared``.

A repository nobody bound to a profile has nothing published to it, a
reviewer nothing allows is not dispatched, and a watched repository
with no boundary on a layer stops the worker. These commands write the
records that decide each, so that nobody writes them into the database
by hand.

Each command prints what the database holds afterwards, read back and
not echoed, so a run that wrote nothing prints nothing new. A refusal
is written to the error stream and returns 2, and nothing is written.
"""

import sys
from dataclasses import dataclass
from datetime import datetime
from typing import TextIO

from bugflow.apps.shared.deploying import declared_by_deployment
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.method.domain.models.boundary import (
    BoundaryError,
    phase,
    settling_window,
)
from bugflow.method.domain.models.pace_layer import CADENCES, EVENT
from bugflow.method.infrastructure.sqlalchemy_policy_deployments import (
    SqlAlchemyPolicyDeployments,
)
from bugflow.review.domain.models.cadence_boundary import CadenceBoundary
from bugflow.review.domain.models.enforcement import PROFILES
from bugflow.review.domain.models.layer_boundary import LayerBoundary
from bugflow.review.domain.models.review_declaration import (
    DispatchedProcesses,
    JudgedPolicies,
)
from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.domain.models.withholding import Withholding
from bugflow.review.infrastructure.sqlalchemy_cadence_boundaries import (
    SqlAlchemyCadenceBoundaries,
)
from bugflow.review.infrastructure.sqlalchemy_enforcement import (
    SqlAlchemyEnforcement,
)
from bugflow.review.infrastructure.sqlalchemy_layer_boundaries import (
    SqlAlchemyLayerBoundaries,
)
from bugflow.review.infrastructure.sqlalchemy_review_declaration import (
    SqlAlchemyDispatchedProcesses,
    SqlAlchemyJudgedPolicies,
)
from bugflow.review.infrastructure.sqlalchemy_spend_bindings import (
    SqlAlchemySpendBindings,
)
from bugflow.review.infrastructure.sqlalchemy_withholding import (
    SqlAlchemyWithholding,
)
from bugflow.shared.domain.values.budget import Budget
from bugflow.shared.infrastructure.system_clock import SystemClock


class Unnamed:
    """A resource the call said nothing about.

    Distinct from None, which is a resource the call said has no limit.
    Without the distinction a write has to invent a figure for whatever
    it was not asked about, and a call naming only the dollars would
    replace an unlimited turn allowance with a default.
    """


#: The one instance, so a default argument reads as what it means.
UNNAMED = Unnamed()


@dataclass(frozen=True)
class Console:
    """Where a command prints what is held, and where it refuses."""

    out: TextIO
    err: TextIO

    def say(self, line: str) -> None:
        print(line, file=self.out)

    def refuse(self, reason: str) -> int:
        """Write the refusal and return the exit status of one."""
        print(f"error: {reason}", file=self.err)
        return 2


def _console(out: TextIO | None, err: TextIO | None) -> Console:
    return Console(out=out or sys.stdout, err=err or sys.stderr)


def _split(name: str) -> tuple[str, str]:
    """Return the forge and ``owner/name`` the records hold a
    repository by. Raises ``ValueError`` for a name that is neither
    ``owner/name`` nor ``forgejo:owner/name``."""
    repository = WatchedRepository.parse(name)
    return repository.forge, f"{repository.owner}/{repository.repo}"


def _unreadable(boundary: str, zone: str, now: datetime) -> str | None:
    """Say why the text is no boundary of either kind, or return None
    for one that reads as a settling window or as a phase.

    Which kind a layer takes is the topology's to say, and a boundary
    may be declared before any deployment is in force, so this checks
    the shape and not the layer.
    """
    try:
        settling_window(boundary)
    except BoundaryError:
        pass
    else:
        return None
    try:
        phase(boundary, "day", now, zone)
    except BoundaryError:
        return (
            f"{boundary!r} is no boundary. For a layer an event fires, "
            "write the window its deliveries settle in as seconds, such "
            "as 60s. For a layer a clock fires, write a time, a day and "
            "a time, a day of the month and a time, or a date and a "
            "time, such as SUN 23:30"
        )
    return None


def run_declare(
    database_url: str,
    repository: str,
    policies: list[str] | None = None,
    processes: list[str] | None = None,
    profile: str | None = None,
    layer: str = "",
    boundary: str | None = None,
    withhold: float | None = None,
    zone: str = "UTC",
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Declare what a repository is judged on and dispatches, its
    profile, a boundary and its withheld share, and print what is held.

    Only what the call names is written. A set that is named is written
    whole, because a declaration is a set: a name left out of it is no
    longer declared. None is not named; an empty list is named and
    declares nothing. ``boundary`` empty withdraws the layer's.

    ``zone`` is the timezone a boundary is read in, to refuse one that
    does not read.
    """
    console = _console(out, err)
    try:
        forge, repo = _split(repository)
    except ValueError as exc:
        return console.refuse(str(exc))
    if (
        policies is None
        and processes is None
        and profile is None
        and boundary is None
        and withhold is None
    ):
        return console.refuse(
            "name --policy, --process, --profile, --boundary, --withhold, "
            "--no-policies or --no-processes: a call that names none of "
            "them declares nothing"
        )
    if (
        policies is not None or processes is not None
    ) and declared_by_deployment(SqlAlchemyPolicyDeployments(database_url)):
        return console.refuse(
            "the policy deployment in force carries declarations.toml, so "
            "what a repository is judged on and what it dispatches are "
            "changed in the policy repository and deployed from there; "
            "--policy, --process, --no-policies and --no-processes are "
            "refused"
        )
    if boundary is not None and not layer:
        return console.refuse(
            "--boundary needs --layer: a boundary is where one layer's "
            "period begins for this repository, and two layers of one "
            "repository begin in different places"
        )
    if boundary:
        unreadable = _unreadable(boundary, zone, SystemClock().now())
        if unreadable:
            return console.refuse(unreadable)
    if profile is not None and profile not in PROFILES:
        return console.refuse(
            f"{profile!r} is no profile; "
            f"name one of {', '.join(sorted(PROFILES))}"
        )
    if withhold is not None:
        try:
            share = Withholding(forge=forge, repo=repo, share=withhold)
        except ValueError as exc:
            return console.refuse(str(exc))

    judged = SqlAlchemyJudgedPolicies(database_url)
    dispatched = SqlAlchemyDispatchedProcesses(database_url)
    enforcement = SqlAlchemyEnforcement(database_url)
    boundaries = SqlAlchemyLayerBoundaries(database_url)
    withholding = SqlAlchemyWithholding(database_url)
    if boundary:
        boundaries.declare(
            LayerBoundary(
                forge=forge, repo=repo, layer=layer, boundary=boundary
            )
        )
    elif boundary is not None:
        boundaries.withdraw(forge, repo, layer)
    if withhold is not None:
        withholding.declare(share)
    if profile is not None:
        enforcement.bind(forge, repo, PROFILES[profile])
    if policies is not None:
        judged.declare(
            JudgedPolicies(forge=forge, repo=repo, policies=tuple(policies))
        )
    if processes is not None:
        dispatched.declare(
            DispatchedProcesses(
                forge=forge, repo=repo, processes=tuple(processes)
            )
        )

    where = f"{forge}:{repo}"
    console.say(_judged(where, judged.judged(forge, repo)))
    console.say(_dispatches(where, dispatched.dispatched(forge, repo)))
    if layer:
        at = boundaries.boundary(forge, repo, layer)
        console.say(
            _begins(where, layer, at)
            if at
            else f"{where} has no boundary on {layer}, and a worker "
            "watching it on that layer does not start"
        )
    console.say(_profile(where, enforcement.profile_for(forge, repo).name))
    console.say(_withholds(where, withholding.share_for(forge, repo)))
    return 0


def _judged(where: str, policies: frozenset[str] | tuple[str, ...]) -> str:
    return f"{where} is judged on {', '.join(sorted(policies)) or 'nothing'}"


def _dispatches(
    where: str, processes: frozenset[str] | tuple[str, ...]
) -> str:
    return f"{where} dispatches {', '.join(sorted(processes)) or 'nothing'}"


def _begins(where: str, layer: str, boundary: str) -> str:
    return f"{where} begins its {layer} period at {boundary}"


def _profile(where: str, name: str) -> str:
    return f"{where} is on the {name} profile"


def _withholds(where: str, share: float) -> str:
    if share <= 0:
        return f"{where} withholds no warnings"
    return (
        f"{where} withholds {share:.0%} of its warnings, drawn by "
        "finding, so what becomes of them can be measured"
    )


def _server_begins(cadence: str, boundary: str) -> str:
    return f"this server begins its {cadence} periods at {boundary}"


def _scope(
    repository: str, layer: str, agent: str
) -> tuple[SpendScope, str] | str:
    """Return the scope an allowance is bound to and its name, or the
    reason the repository is not one."""
    forge, repo = "", ""
    if repository:
        try:
            forge, repo = _split(repository)
        except ValueError as exc:
            return str(exc)
    return (
        SpendScope(forge=forge, repo=repo, layer=layer, agent_id=agent),
        where_of(forge, repo, layer, agent),
    )


def _not_a_cadence(per: str) -> str | None:
    if per in CADENCES:
        return None
    return (
        f"{per!r} is not a cadence; an allowance is per cadence, and "
        f"the cadences are: {', '.join(CADENCES)}"
    )


def run_allow(
    database_url: str,
    repository: str = "",
    usd: float | Unnamed | None = UNNAMED,
    turns: float | Unnamed | None = UNNAMED,
    layer: str = "",
    agent: str = "",
    per: str = EVENT.name,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Bind what a run of that scope may spend, and print what is held.

    An empty repository, layer or agent means any, and every allowance
    whose scope covers a run applies to it.

    A resource the call names is written; one it does not name is left
    as it was. A call that names neither is refused, and so is a call
    that names one where the scope holds no allowance for that cadence:
    there is nothing to leave alone, and a figure for the other would
    be one nobody asked for.
    """
    console = _console(out, err)
    refusal = _not_a_cadence(per)
    if refusal:
        return console.refuse(refusal)
    money = not isinstance(usd, Unnamed)
    turning = not isinstance(turns, Unnamed)
    if not (money or turning):
        return console.refuse(
            "name --usd, --turns, --no-money-limit or --no-turn-limit: "
            "a call that names neither resource says nothing about "
            "what may be spent"
        )
    found = _scope(repository, layer, agent)
    if isinstance(found, str):
        return console.refuse(found)
    scope, where = found
    bindings = SqlAlchemySpendBindings(database_url)
    held = _held(bindings, scope, per)
    if held is None:
        if not (money and turning):
            return console.refuse(
                "this scope has no allowance for that cadence, so there "
                "is nothing to leave alone: name both resources, with "
                "--usd or --no-money-limit and --turns or --no-turn-limit"
            )
        held = Budget(usd=None, turns=None)
    bindings.declare(
        SpendBinding(
            scope=scope,
            budget=Budget(
                usd=held.usd if isinstance(usd, Unnamed) else usd,
                turns=held.turns if isinstance(turns, Unnamed) else turns,
            ),
            per=per,
        )
    )
    console.say(_said(where, _held(bindings, scope, per), per))
    if (
        CADENCES[per].on_a_clock
        and SqlAlchemyCadenceBoundaries(database_url).boundary(per) is None
    ):
        console.say(
            f"this server has no {per} boundary. Unless the repository "
            f"declared its own on a layer of that cadence, this allowance "
            f"refuses every run it covers until one is declared with "
            f"`bugflow cadence {per} --boundary BOUNDARY`"
        )
    return 0


def _held(
    bindings: SqlAlchemySpendBindings, scope: SpendScope, per: str
) -> Budget | None:
    """Return the allowance this scope holds for that cadence, matched
    by its whole key: a scope holds one allowance per cadence, and
    matching the scope alone finds whichever comes back first."""
    return next(
        (
            one.budget
            for one in bindings.binding_for(
                scope.forge, scope.repo, scope.layer, scope.agent_id
            )
            if one.scope == scope and one.per == per
        ),
        None,
    )


def run_revoke(
    database_url: str,
    repository: str = "",
    layer: str = "",
    agent: str = "",
    per: str = EVENT.name,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Remove one allowance, and print what the scope is left with.

    Removing is not binding zero: zero is an allowance that refuses
    everything, and removing leaves the scope to whatever wider
    allowances still cover it.
    """
    console = _console(out, err)
    refusal = _not_a_cadence(per)
    if refusal:
        return console.refuse(refusal)
    found = _scope(repository, layer, agent)
    if isinstance(found, str):
        return console.refuse(found)
    scope, where = found
    bindings = SqlAlchemySpendBindings(database_url)
    bindings.revoke(scope, per)
    left = [
        one
        for one in bindings.binding_for(
            scope.forge, scope.repo, scope.layer, scope.agent_id
        )
        if one.scope == scope
    ]
    console.say(f"{where} is no longer allowed anything per {per}")
    if not left:
        console.say(
            f"{where} has no allowance of its own, and spends what any "
            "wider allowance covering it allows"
        )
        return 0
    console.say("what it still has:")
    for one in left:
        console.say(f"  {_said(where, one.budget, one.per)}")
    return 0


def where_of(forge: str, repo: str, layer: str, agent: str) -> str:
    """Name a scope as a person does: its named parts, or
    ``everything`` for a scope that names none."""
    return (
        " ".join(
            part
            for part in (f"{forge}:{repo}" if repo else "", layer, agent)
            if part
        )
        or "everything"
    )


def _said(where: str, found: Budget | None, per: str) -> str:
    """Say what an allowance allows, and how it is kept.

    A limit per event is the ceiling handed to the run, and the runner
    is held to it while it works. A limit per period is asked before a
    run starts, about what the scope has already spent, and the run is
    refused when that leaves no room.
    """
    if found is None:
        return f"{where} is allowed nothing"
    money = "unlimited money" if found.usd is None else f"${found.usd:.2f}"
    turns = (
        "unlimited turns"
        if found.turns is None
        else f"{found.turns:.0f} turns"
    )
    figures = f"{money} and {turns}"
    if per == EVENT.name:
        return (
            f"{where} may spend {figures} per {EVENT.name}, which the "
            "runner is held to while it works"
        )
    return (
        f"{where} may spend {figures} per {per}, and a run is refused "
        f"once the {per} allowance is spent"
    )


def run_declared(
    database_url: str,
    repository: str = "",
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Print every declaration and every allowance the database holds.

    With a repository, print only what bears on it: its own
    declarations, every allowance that covers it, and this server's
    cadence boundaries.
    """
    console = _console(out, err)
    only: tuple[str, str] | None = None
    if repository:
        try:
            only = _split(repository)
        except ValueError as exc:
            return console.refuse(str(exc))

    def wanted(forge: str, repo: str) -> bool:
        return only is None or (forge, repo) == only

    lines = [
        _judged(f"{one.forge}:{one.repo}", one.policies)
        for one in SqlAlchemyJudgedPolicies(database_url).declarations()
        if wanted(one.forge, one.repo)
    ]
    lines += [
        _dispatches(f"{sent.forge}:{sent.repo}", sent.processes)
        for sent in SqlAlchemyDispatchedProcesses(database_url).declarations()
        if wanted(sent.forge, sent.repo)
    ]
    lines += [
        _profile(f"{forge}:{repo}", profile.name)
        for (forge, repo), profile in SqlAlchemyEnforcement(database_url)
        .bindings()
        .items()
        if wanted(forge, repo)
    ]
    for binding in SqlAlchemySpendBindings(database_url).bindings():
        scope = binding.scope
        if not scope.repo or wanted(scope.forge, scope.repo):
            where = where_of(
                scope.forge, scope.repo, scope.layer, scope.agent_id
            )
            lines.append(_said(where, binding.budget, binding.per))
    lines += [
        _server_begins(ours.cadence, ours.boundary)
        for ours in SqlAlchemyCadenceBoundaries(database_url).declarations()
    ]
    lines += [
        _begins(f"{theirs.forge}:{theirs.repo}", theirs.layer, theirs.boundary)
        for theirs in SqlAlchemyLayerBoundaries(database_url).declarations()
        if wanted(theirs.forge, theirs.repo)
    ]
    lines += [
        _withholds(f"{drawn.forge}:{drawn.repo}", drawn.share)
        for drawn in SqlAlchemyWithholding(database_url).declarations()
        if wanted(drawn.forge, drawn.repo)
    ]
    if not lines:
        console.say(
            "nothing is declared and nothing is allowed"
            + (f" for {only[0]}:{only[1]}" if only else "")
        )
        return 0
    for line in lines:
        console.say(line)
    return 0


def run_cadence(
    database_url: str,
    cadence: str,
    boundary: str | None = None,
    zone: str = "UTC",
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Declare where this server's periods of one cadence begin, and
    print what is held.

    It is what an allowance scoped wider than one repository and one
    layer is counted over, and what a repository that declared none
    falls back to. None reads what is held and writes nothing; empty
    withdraws it, and every allowance counted per that cadence then
    refuses until one is declared.

    ``zone`` is the timezone the boundary is read in, to refuse one
    that does not read.
    """
    console = _console(out, err)
    found = CADENCES.get(cadence)
    if found is None:
        return console.refuse(
            f"{cadence!r} is not a cadence; the cadences are: "
            f"{', '.join(CADENCES)}"
        )
    if not found.span:
        return console.refuse(
            f"no clock fires the {cadence} cadence, so it has no period "
            "for this server to bound; a repository bounds it on a layer, "
            "with `bugflow declare REPOSITORY --layer LAYER --boundary "
            "BOUNDARY`"
        )
    declared = SqlAlchemyCadenceBoundaries(database_url)
    if boundary:
        try:
            phase(boundary, found.span, SystemClock().now(), zone)
        except BoundaryError as exc:
            return console.refuse(str(exc))
        declared.declare(CadenceBoundary(cadence=cadence, boundary=boundary))
    elif boundary is not None:
        declared.withdraw(cadence)
    at = declared.boundary(cadence)
    console.say(
        _server_begins(cadence, at)
        if at
        else f"this server has no {cadence} boundary, and every allowance "
        f"counted per {cadence} refuses until one is declared"
    )
    return 0
