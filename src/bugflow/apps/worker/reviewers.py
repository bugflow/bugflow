"""What a worker settles about its reviewers before it runs one: which
it dispatches and where, what a run may spend, and the periods an
allowance is counted over.

A reviewer is its prose, and the prose is what a run is asked. The
reviewers come from the policy deployment in force, and the functions
here turn them into what an activity needs, so that an activity does
not know where a reviewer is kept.
"""

import hashlib
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bugflow.apps.worker.corpus import checking_fingerprint
from bugflow.method.domain.models.boundary import BoundaryError, phase
from bugflow.method.domain.models.corpus import AgentCorpus
from bugflow.method.domain.models.pace_layer import CADENCES, EVENT, PaceLayer
from bugflow.method.domain.models.policy_text import PolicyText
from bugflow.method.infrastructure.reviewer_packages import (
    DomainSpecificReviewAgent,
)
from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.domain.services.cadence_boundaries import (
    CadenceBoundariesService,
)
from bugflow.review.domain.services.layer_boundaries import (
    LayerBoundariesService,
)
from bugflow.review.domain.services.review_declaration import (
    DispatchedProcessesService,
    JudgedPoliciesService,
)
from bugflow.review.domain.services.spend_bindings import (
    SpendBindingsService,
)
from bugflow.review.domain.services.spend_record import (
    SpendRecordService,
)
from bugflow.shared.domain.values.budget import Budget, allowance, period


@dataclass(frozen=True)
class ReviewerSettings:
    """One reviewer, ready to dispatch."""

    agent_id: str
    instructions: str
    # What the process declared this work is worth, which caps what the
    # deployment allows and does not allow anything by itself. None if
    # the process declared nothing.
    worth: Budget | None = None
    # The layer this reviewer was made dispatchable for, which is half
    # of what a binding is looked up by. Empty if the caller built these
    # without a layer, and a binding scoped to a layer then matches
    # nothing.
    layer: str = ""


def dispatchable(
    agents: dict[str, DomainSpecificReviewAgent],
    runner: str,
    held: Collection[str],
    layer: str = "",
    worth: Mapping[str, Budget] | None = None,
) -> dict[str, ReviewerSettings]:
    """Return the installed reviewers this worker dispatches at this
    layer.

    Two things narrow it. A reviewer whose manifest names another runner
    is not this worker's to run: one that names the judge is not
    dispatched at a checkout. And a reviewer no process of this layer
    names is not run here, which is how the topology moves a reviewer
    from one cadence to another.

    ``worth`` is what each reviewer's process declared its work is
    worth, by reviewer. A process that declared nothing leaves it None.
    """
    declared = worth or {}
    return {
        agent_id: ReviewerSettings(
            agent_id=agent_id,
            instructions=agent.description,
            worth=declared.get(agent_id),
            layer=layer,
        )
        for agent_id, agent in agents.items()
        if agent.runner == runner and agent_id in held
    }


def verdict_scope(
    agents: Mapping[str, DomainSpecificReviewAgent],
    answered: Iterable[str],
) -> dict[str, tuple[str, ...]]:
    """Return what each installed reviewer's verdict covers: the policies
    it declared that this server answers.

    Everything that builds a label builds it from this, with the same
    answered set, so that a replay reaches the label a live evaluation
    would.
    """
    answering = set(answered)
    return {
        agent_id: tuple(p for p in agent.policies if p in answering)
        for agent_id, agent in agents.items()
    }


def governing_by_default(
    agents: Mapping[str, DomainSpecificReviewAgent],
) -> tuple[str, ...]:
    """Return the reviewers whose manifest says they govern, for a
    repository nobody has decided about."""
    return tuple(
        agent_id for agent_id, agent in agents.items() if agent.governs
    )


def policy_summaries(
    policies: Mapping[str, Mapping[str, PolicyText]],
) -> dict[str, str]:
    """Return each installed policy's summary, the rule in a sentence, by
    policy id.

    ``policies`` is each reviewer's parsed policies, by reviewer id then
    policy id, as the deployment in force holds them. A comment names
    the rule a passage breaks by its summary. A reviewer with no policy
    contributes none.
    """
    return {
        policy_id: policy.summary
        for of_agent in policies.values()
        for policy_id, policy in of_agent.items()
    }


def corpus_of(
    agents: Mapping[str, DomainSpecificReviewAgent],
    prose: Mapping[str, str],
    pinned: Mapping[str, str | None],
) -> tuple[AgentCorpus, ...]:
    """Return each installed reviewer's own corpus, in id order.

    ``prose`` is everything each reviewer's prose says, by reviewer id:
    its manifest, its policies and its doctrine, as the deployment in
    force holds them. Contents and never paths, so moving a file moves
    no version.

    ``pinned`` is a fingerprint per runner name, of the thing that runs
    a reviewer on this server: the judge's model and adapter, or a
    checkout runner's. A reviewer whose runner is not set up here has
    none.

    A reviewer whose manifest has a ``checks`` line carries the
    fingerprint of the code that answers a checked policy. Which policy
    a check answers is the manifest's to say, so no policy is named
    here.
    """
    return tuple(
        AgentCorpus(
            agent_id=agent_id,
            prose=hashlib.sha256(prose[agent_id].encode()).hexdigest()[:12],
            runner=agent.runner,
            pinned=pinned.get(agent.runner),
            checks=checking_fingerprint() if agent.checks else None,
        )
        for agent_id, agent in sorted(agents.items())
    )


def allowance_for(
    ceilings: SpendBindingsService | None,
    forge: str,
    repo: str,
    settings: ReviewerSettings,
) -> Budget | None:
    """Return what one dispatch may spend, or None if nothing allowed it.

    The deployment's binding is read now and not when the worker
    started: a ceiling read once could not be lowered without a restart.
    What the process declared caps it and does not allow anything on its
    own.

    None if no binding matches, and if no bindings are set up at all. A
    deployment that has bound nothing spends nothing, which is the
    direction it is safe to be wrong in.
    """
    if ceilings is None:
        return None
    bound = ceilings.binding_for(
        forge, repo, settings.layer, settings.agent_id
    )
    # Only what is spent per run holds a run. A period allowance is a
    # question about what a scope has already spent, which ``out_of_room``
    # asks, and reading it as a per-run ceiling would hold one review to
    # a week's allowance.
    return allowance(
        (one.budget for one in bound if one.per == EVENT.name),
        settings.worth,
    )


#: The timezone a calendar period starts and ends in when the
#: ``PERIODS_TIMEZONE`` setting is not given.
DEFAULT_PERIODS_TIMEZONE = "UTC"


def periods_timezone(environ: Mapping[str, str]) -> str:
    """Read the timezone a calendar period starts and ends in.

    Setting: ``PERIODS_TIMEZONE``, an IANA name such as
    ``Europe/Lisbon``. It defaults to ``UTC``. A server has one, so that
    a day's allowance and a weekly run are counted on the same clock.

    Raises ``ValueError`` if the name is not a timezone.
    """
    name = environ.get("PERIODS_TIMEZONE") or DEFAULT_PERIODS_TIMEZONE
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(
            f"PERIODS_TIMEZONE is {name!r}, which is not a timezone"
        ) from exc
    return name


@dataclass(frozen=True)
class Boundaries:
    """Where the periods an allowance is counted over begin.

    A boundary belongs to the repository whose period it bounds, and an
    allowance may be scoped wider than any repository. So two
    declarations answer, and this is where they meet: the repository's
    if the allowance names one repository and one layer riding the
    cadence it is counted per, and the deployment's otherwise.

    The layers are here because a boundary is declared per layer and an
    allowance is counted per cadence, and only the topology says which
    layer rides which.
    """

    layers: Mapping[str, PaceLayer]
    repositories: LayerBoundariesService | None = None
    deployment: CadenceBoundariesService | None = None
    #: The timezone a calendar period starts and ends in, as
    #: ``periods_timezone`` reads it.
    zone: str = DEFAULT_PERIODS_TIMEZONE

    def bounding(self, binding: SpendBinding) -> str | None:
        """Return where this allowance's periods begin, or None if
        nothing has said."""
        scope = binding.scope
        layer = self.layers.get(scope.layer)
        if (
            self.repositories is not None
            and scope.forge
            and scope.repo
            and layer is not None
            and layer.cadence.name == binding.per
        ):
            declared = self.repositories.boundary(
                scope.forge, scope.repo, scope.layer
            )
            if declared is not None:
                return declared
        if self.deployment is None:
            return None
        return self.deployment.boundary(binding.per)

    def window(
        self, binding: SpendBinding, now: datetime
    ) -> tuple[datetime, datetime] | None:
        """Return the period of this allowance that contains ``now``.

        None if the cadence has no span, which is the cadence no clock
        fires: a per-event allowance is the ceiling handed to the run
        and not a question about what was already spent.

        Raises ``BoundaryError`` if nothing says where the period
        begins.
        """
        cadence = CADENCES.get(binding.per)
        if cadence is None or not cadence.span:
            return None
        declared = self.bounding(binding)
        if declared is None:
            raise BoundaryError(
                f"nothing says where a {binding.per} period begins for "
                f"{where_named(binding.scope) or 'everything'}"
            )
        begins = phase(declared, cadence.span, now, self.zone)
        return period(cadence.span, begins.at, now)


def refused_by(
    ceilings: SpendBindingsService | None,
    spend: SpendRecordService | None,
    boundaries: Boundaries,
    now: datetime,
    forge: str,
    repo: str,
    settings: ReviewerSettings,
) -> str | None:
    """Say which period allowance has no room left for this reviewer,
    or return None if every one has room."""
    return out_of_room(
        ceilings,
        spend,
        boundaries,
        now,
        forge,
        repo,
        settings.layer,
        settings.agent_id,
    )


def out_of_room(
    ceilings: SpendBindingsService | None,
    spend: SpendRecordService | None,
    boundaries: Boundaries,
    now: datetime,
    forge: str,
    repo: str,
    layer: str = "",
    agent_id: str = "",
) -> str | None:
    """Say which period allowance covering that scope has no room left,
    or return None if every one has room.

    Every allowance that matches applies, and one measured over a
    period is a question about what its scope has already spent. Work
    happens when every one of them has room. When one does not, this
    says which, because "out of budget" without a scope sends a reader
    to the wrong place.

    It is asked of a scope and not of a reviewer, because judging
    spends and names no reviewer: a backfill judges every pull request
    it reads.

    None if nothing is set up to answer either question, which leaves
    the ceiling on one run to decide alone: a deployment without the
    spend record is not thereby over every limit.
    """
    if ceilings is None or spend is None:
        return None
    for binding in ceilings.binding_for(forge, repo, layer, agent_id):
        if binding.budget.usd is None:
            continue
        try:
            window = boundaries.window(binding, now)
        except BoundaryError as unbounded:
            # A ceiling nothing can count is not a ceiling that does not
            # apply. Refusing names it. Skipping would spend under a
            # limit nobody is measuring.
            return str(unbounded)
        if window is None:
            continue
        scope = binding.scope
        already = spend.spent(
            *window,
            forge=scope.forge,
            repo=scope.repo,
            layer=scope.layer,
            agent_id=scope.agent_id,
        )
        if already.usd >= binding.budget.usd:
            where = where_named(scope) or "everything"
            return (
                f"{where} is allowed ${binding.budget.usd:.2f} per "
                f"{binding.per} and has spent ${already.usd:.2f}"
            )
    return None


def judging_over_ceiling(
    ceilings: SpendBindingsService | None,
    spend: SpendRecordService | None,
    run_id: str,
    forge: str,
    repo: str,
    layer: str = "",
) -> str | None:
    """Say why this run may judge no more, or return None while it may.

    Judging is spending and is capped like any other. The ceiling is
    the allowance per run for this repository and layer with no
    reviewer named, because judging is the evaluation itself and names
    none. What the run has spent is every cost it has recorded, since
    an allowance per run is what one run may spend and not what one
    kind of spending may.

    None if nothing is set up to answer either question, and if no
    binding limits money: a deployment without the spend record is not
    thereby over every limit, which is how ``out_of_room`` reads the
    same silence.
    """
    if ceilings is None or spend is None or not run_id:
        return None
    bound = [
        one.budget.usd
        for one in ceilings.binding_for(forge, repo, layer, "")
        if one.per == EVENT.name and one.budget.usd is not None
    ]
    if not bound:
        return None
    ceiling = min(bound)
    already = spend.spent_in_run(run_id)
    if already.usd < ceiling:
        return None
    return (
        f"this run is allowed ${ceiling:.2f} and has spent ${already.usd:.2f}"
    )


def where_named(scope: SpendScope) -> str:
    """Name the scope as a person does, for a refusal that has to be
    read."""
    return " ".join(
        part
        for part in (
            f"{scope.forge}:{scope.repo}" if scope.repo else "",
            scope.layer,
            scope.agent_id,
        )
        if part
    )


def policies_for(
    held: Sequence[str],
    judged: JudgedPoliciesService | None,
    forge: str,
    repo: str,
) -> list[str]:
    """Return which of this worker's policies to judge for that
    repository.

    What a repository is reviewed for is declared per repository, so
    the worker's set is narrowed by the repository's. A repository that
    declared nothing is judged on nothing, which is the default and
    costs nothing.

    A policy a repository declared that this worker has no judge for is
    left out as well: a judge that cannot answer is not an answer, and
    fanning out to it reports a policy as unavailable when the server
    never had it.

    ``judged`` is None if no declarations are set up at all, which is
    not the same as a deployment that declared nothing: the worker then
    judges everything it holds.
    """
    if judged is None:
        return list(held)
    declared = judged.judged(forge, repo)
    return [one for one in held if one in declared]


def reviewers_for(
    held: Sequence[str],
    dispatched: DispatchedProcessesService | None,
    named: Mapping[str, str],
    forge: str,
    repo: str,
) -> list[str]:
    """Return which of a layer's reviewers to dispatch for that
    repository.

    The layer says which processes exist and the repository says which
    of them apply to it. A reviewer is named by a process, so
    the narrowing is by process: two layers may run the same reviewer
    under different processes, and a repository may want one and not
    the other.

    ``named`` maps the layer's reviewers to the process each runs. A
    reviewer the layer names no process for is not dispatched, because
    a repository has no way to declare it.

    ``dispatched`` is None if no declarations are set up at all, and
    the layer's reviewers are then all dispatched, as in
    ``policies_for``.
    """
    if dispatched is None:
        return list(held)
    declared = dispatched.dispatched(forge, repo)
    return [one for one in held if named.get(one, "") in declared]


def reviewers_on(
    layers: Mapping[str, PaceLayer], cadence_name: str
) -> frozenset[str]:
    """Return the reviewers the layers at this cadence hold.

    A reviewer no process names runs nowhere. Moving one between
    cadences is an edit to the topology and not to a server's settings:
    a runner stays set up for the layers that want it.
    """
    return frozenset(
        one.reviewer
        for layer in layers.values()
        if layer.cadence.name == cadence_name
        for one in layer.processes
        if one.reviewer
    )


def reviewers_anywhere(layers: Mapping[str, PaceLayer]) -> frozenset[str]:
    """Return every reviewer any layer holds, at any cadence.

    This decides whether a worker needs a runner at all, which is not
    the same question as which reviewers a delivery dispatches. A
    worker that read only the layer a delivery runs would conclude it
    needed no runner when every reviewer is on a clock, and a run on a
    clock would then have nobody to ask.
    """
    return frozenset(
        one.reviewer
        for layer in layers.values()
        for one in layer.processes
        if one.reviewer
    )


def processes_on(layer: PaceLayer) -> dict[str, str]:
    """Return which process names each of a layer's reviewers.

    A repository declares the processes it dispatches and a fan-out
    names reviewers, so something has to hold the two together. Two
    layers may run the same reviewer under different processes, which
    is why this is per layer.
    """
    return {one.reviewer: one.name for one in layer.processes if one.reviewer}


def worth_on(layer: PaceLayer) -> dict[str, Budget]:
    """Return what each of a layer's reviewers has its work declared
    worth.

    A process that declared nothing is absent, and its reviewer is
    allowed what the deployment bound and no more.
    """
    return {
        one.reviewer: one.worth
        for one in layer.processes
        if one.reviewer and one.worth
    }
