"""The part of the worker that reviews pull requests, built from the
environment and the policy deployment in force.

A server that was never sent a deployment reviews nothing: the part is
then a watcher that stops the worker when one is put in force, so that
the next start reads it. With a deployment in force the part holds the
four review workflows and their activities.

Settings, all optional:

- ``DATABASE_URL``: the Postgres database the deployment, the journal
  and the review records are kept in. Not given, nothing is reviewed.
- ``POLICY_CHECKS``, as ``apps/shared/deploying.py`` reads it.
- ``REVIEW_AGENTS``: the reviewers to run, by id, comma-separated. Not
  given, every reviewer the deployment holds.
- ``FORGE_TOKEN``, ``FORGEJO_URL`` and ``FORGEJO_TOKEN``, as
  ``apps/shared/forges.py`` reads them.
- ``LITELLM_MASTER_KEY``, ``JUDGE_URL``, ``JUDGE_MODEL`` and the classes'
  models, as ``litellm_judge.judge_from_environment`` reads them.
- ``REVIEW_RUNNER``: the name of the runner reviews are dispatched to.
  The runner's own settings are read by
  ``review_agent.managed_agent_from_environment``.
- ``PERIODS_TIMEZONE``, as ``reviewers.periods_timezone`` reads it.
- ``WATCHED_REPOSITORIES``: the repositories a layer on a clock takes
  stock of, comma-separated, each ``owner/repo`` or
  ``forgejo:owner/repo``.
- ``TOKENOMIC_S3_ENDPOINT``, ``TOKENOMIC_S3_BUCKET``,
  ``TOKENOMIC_S3_ACCESS_KEY``, ``TOKENOMIC_S3_SECRET_KEY`` and
  ``TOKENOMIC_S3_REGION``: where the content of each call to a model is
  kept. Not all given, the content is kept nowhere.
- ``BUILD_SHA``, as ``apps/shared/journals.py`` reads it.
"""

import asyncio
import sys
from collections.abc import Callable, Collection, Iterable, Mapping

from temporalio.client import Client

from bugflow.apps.shared.boundaries import refuse_without_a_boundary
from bugflow.apps.shared.deploying import checks_from
from bugflow.apps.shared.forges import forge_token, forgejo_settings
from bugflow.apps.shared.journals import build_sha, review_journal
from bugflow.apps.shared.policies import ReviewersInForce, reviewers_in_force
from bugflow.apps.worker.activities import (
    BackfillActivities,
    Checked,
    ReviewActivities,
)
from bugflow.apps.worker.backfill import BackfillWorkflow
from bugflow.apps.worker.closed_pull_requests import ForgeClosedPullRequests
from bugflow.apps.worker.conversation import ConversingForge
from bugflow.apps.worker.evaluate_pull_request import (
    EvaluatePullRequestWorkflow,
)
from bugflow.apps.worker.forge_by_reference import forge_from_environment
from bugflow.apps.worker.litellm_judge import (
    MODEL_CLASS_VARIABLES,
    LiteLLMJudge,
    judge_from_environment,
    judging_agent,
)
from bugflow.apps.worker.parts import WorkerParts
from bugflow.apps.worker.pull_request import PullRequestWorkflow
from bugflow.apps.worker.review_agent import managed_agent_from_environment
from bugflow.apps.worker.reviewers import (
    Boundaries,
    ReviewerSettings,
    corpus_of,
    dispatchable,
    governing_by_default,
    periods_timezone,
    policy_summaries,
    processes_on,
    reviewers_anywhere,
    reviewers_on,
    verdict_scope,
    worth_on,
)
from bugflow.apps.worker.schedules import TemporalScheduler, reconcile
from bugflow.apps.worker.stocktake import StocktakeWorkflow
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.forge.infrastructure.forgejo import ForgejoForge
from bugflow.forge.infrastructure.github import GitHubForge
from bugflow.forge.infrastructure.sqlalchemy_snapshots import (
    SqlAlchemySnapshotStore,
)
from bugflow.method.domain.models.pace_layer import EVENT
from bugflow.method.domain.models.policy_text import PolicyText
from bugflow.method.infrastructure.deployment_watch import (
    stop_on_new_deployment,
)
from bugflow.method.infrastructure.no_doctrine import NoDoctrine
from bugflow.method.infrastructure.reviewer_packages import (
    DomainSpecificReviewAgent,
)
from bugflow.method.infrastructure.sqlalchemy_policy_deployments import (
    SqlAlchemyPolicyDeployments,
)
from bugflow.review.domain.errors import (
    JudgeTemporarilyUnavailableError,
    JudgeUnavailableError,
)
from bugflow.review.domain.services.enforcement import (
    EnforcementProfileService,
)
from bugflow.review.domain.services.grader import GraderService
from bugflow.review.domain.services.judge import JudgeService
from bugflow.review.infrastructure.sqlalchemy_cadence_boundaries import (
    SqlAlchemyCadenceBoundaries,
)
from bugflow.review.infrastructure.sqlalchemy_enforcement import (
    SqlAlchemyEnforcement,
)
from bugflow.review.infrastructure.sqlalchemy_governance import (
    SqlAlchemyGovernance,
)
from bugflow.review.infrastructure.sqlalchemy_judge_archive import (
    SqlAlchemyJudgeArchive,
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
from bugflow.review.infrastructure.sqlalchemy_spend_record import (
    SqlAlchemySpendRecord,
)
from bugflow.review.infrastructure.sqlalchemy_withholding import (
    SqlAlchemyWithholding,
)
from bugflow.review.infrastructure.sqlalchemy_write_up_archive import (
    SqlAlchemyWriteUpArchive,
)
from bugflow.shared.domain.services.object_store import ObjectStoreService
from bugflow.shared.infrastructure.null_object_store import NullObjectStore
from bugflow.shared.infrastructure.s3_object_store import S3ObjectStore
from bugflow.shared.infrastructure.system_clock import SystemClock
from bugflow.work.domain.repositories.backfill import (
    ClosedPullRequestFeedRepository,
)
from bugflow.work.domain.services.delegated_work import DelegatedWorkService
from bugflow.work.infrastructure.managed_agent import RUNNER as MANAGED_RUNNER
from bugflow.work.infrastructure.sqlalchemy_journal_queries import (
    SqlAlchemyJournalQueries as WorkJournalQueries,
)

#: The workflows this part registers.
WORKFLOWS: tuple[type, ...] = (
    EvaluatePullRequestWorkflow,
    PullRequestWorkflow,
    BackfillWorkflow,
    StocktakeWorkflow,
)

#: The name the stocktake workflow is registered under, which a
#: schedule starts it by.
STOCKTAKE_WORKFLOW = "StocktakeWorkflow"


def object_store_from_environment(
    environ: Mapping[str, str],
) -> ObjectStoreService:
    """Build the store the content of each call to a model is kept in.

    Settings: ``TOKENOMIC_S3_ENDPOINT``, ``TOKENOMIC_S3_BUCKET``,
    ``TOKENOMIC_S3_ACCESS_KEY`` and ``TOKENOMIC_S3_SECRET_KEY``, and
    ``TOKENOMIC_S3_REGION``, which has a default. If the first four are
    not all given the store keeps nothing: every cost is still recorded
    in the journal, and only the content is absent.
    """
    endpoint = environ.get("TOKENOMIC_S3_ENDPOINT", "")
    bucket = environ.get("TOKENOMIC_S3_BUCKET", "")
    access_key = environ.get("TOKENOMIC_S3_ACCESS_KEY", "")
    secret_key = environ.get("TOKENOMIC_S3_SECRET_KEY", "")
    if not (endpoint and bucket and access_key and secret_key):
        return NullObjectStore()
    return S3ObjectStore(
        endpoint=endpoint,
        bucket=bucket,
        access_key=access_key,
        secret_key=secret_key,
        region=environ.get("TOKENOMIC_S3_REGION") or "us-east-1",
    )


def _listed(environ: Mapping[str, str], variable: str) -> tuple[str, ...]:
    return tuple(
        name.strip()
        for name in environ.get(variable, "").split(",")
        if name.strip()
    )


def reviewer_names(environ: Mapping[str, str]) -> tuple[str, ...]:
    """Read the reviewer ids ``REVIEW_AGENTS`` names, or none to mean
    every reviewer the deployment holds."""
    return _listed(environ, "REVIEW_AGENTS")


def watched_repositories(environ: Mapping[str, str]) -> tuple[str, ...]:
    """Read the repositories ``WATCHED_REPOSITORIES`` names, each as the
    journal names it: ``forge:owner/repo``.

    A layer on a clock names no repository, so these are what a
    stocktake is scheduled for.

    Raises ``ValueError`` for a name that is not ``owner/repo`` or
    ``forgejo:owner/repo``.
    """
    watched = (
        WatchedRepository.parse(name)
        for name in _listed(environ, "WATCHED_REPOSITORIES")
    )
    return tuple(f"{one.forge}:{one.owner}/{one.repo}" for one in watched)


def judged_texts(reviewers: ReviewersInForce) -> Mapping[str, PolicyText]:
    """Return the policies the judge has a text for, by policy id:
    those of the reviewer the judge answers for. Empty if the
    deployment holds no such reviewer."""
    agent_id = judging_agent(reviewers)
    return reviewers.policies[agent_id] if agent_id is not None else {}


def checked_policies(
    agents: Mapping[str, DomainSpecificReviewAgent],
) -> dict[str, Checked]:
    """Return the policies a check answers, by policy id, as the
    ``checks`` line of each reviewer's manifest gives them."""
    return {
        check.policy_id: Checked(agent_id=agent_id, clause=check.clause)
        for agent_id, agent in sorted(agents.items())
        for check in agent.checks
    }


def answered_policies(reviewers: ReviewersInForce) -> frozenset[str]:
    """Return every policy this deployment answers: those the judge has
    a text for, and those a check answers."""
    return frozenset(judged_texts(reviewers)) | frozenset(
        checked_policies(reviewers.agents)
    )


def declared_policies(reviewers: ReviewersInForce) -> tuple[str, ...]:
    """Return the judged policies the installed reviewers declared.

    A manifest names every policy its reviewer answers for, and the
    judge has a text for some of them. Those are what a reviewer's
    verdict covers, so they must each have a model before the worker
    starts.
    """
    judged = set(judged_texts(reviewers))
    declared = {
        policy
        for agent in reviewers.agents.values()
        for policy in agent.policies
    }
    return tuple(sorted(declared & judged))


def policy_classes(reviewers: ReviewersInForce) -> dict[str, str]:
    """Return the class of model each judged policy costs, by policy.

    A policy declares its class in its file. A policy answered without
    a model declares none and is absent, and its answer runs on the
    task queue.
    """
    return {
        policy_id: policy.model_class
        for policy_id, policy in judged_texts(reviewers).items()
        if policy.model_class
    }


def reviewing_from_environment(
    environ: Mapping[str, str],
    agents: dict[str, DomainSpecificReviewAgent],
    held: Collection[str],
    served: Collection[str] | None = None,
    agent: DelegatedWorkService | None = None,
) -> tuple[dict[str, ReviewerSettings], DelegatedWorkService | None]:
    """Return the reviewers a delivery dispatches and the runner they
    are dispatched to, or no reviewer and no runner.

    Setting: ``REVIEW_RUNNER`` names the runner. This package has one,
    the managed agent, whose own settings are read by
    ``managed_agent_from_environment``. ``agent`` is a runner the
    caller built, and is used in place of the setting.

    ``held`` is the reviewers the layer a delivery fires holds, and is
    what comes back. ``served`` is every reviewer any layer holds, which
    decides whether a runner is needed at all. They differ if the
    topology puts a reviewer on a clock and not on a delivery.

    Short of what the runner needs, there is no runner and nothing is
    dispatched: the label stays in progress for the reviewers that
    would have run.

    Raises ``ValueError`` if a reviewer some layer holds names a runner
    this worker does not have. A deployment that asked for a reviewer
    and got none would otherwise report a pull request as reviewed by
    whoever happened to be there.
    """
    runner = agent.runner if agent else environ.get("REVIEW_RUNNER", "")
    served = held if served is None else served
    if not runner or not dispatchable(agents, runner, served):
        return {}, None
    dispatch = dispatchable(agents, runner, held)
    if agent is not None:
        return dispatch, agent
    if runner == MANAGED_RUNNER:
        return dispatch, managed_agent_from_environment(
            environ, object_store_from_environment(environ)
        )
    raise ValueError(
        f"REVIEW_RUNNER is {runner!r}, and the only runner this worker "
        f"has is {MANAGED_RUNNER!r}"
    )


def boundaries_from_environment(
    environ: Mapping[str, str], reviewers: ReviewersInForce
) -> Boundaries:
    """Build where the periods an allowance is counted over begin: each
    repository's declaration, this server's own, the layers that join
    them, and the timezone ``PERIODS_TIMEZONE`` names."""
    database_url = environ["DATABASE_URL"]
    return Boundaries(
        layers=reviewers.layers,
        repositories=SqlAlchemyLayerBoundaries(database_url),
        deployment=SqlAlchemyCadenceBoundaries(database_url),
        zone=periods_timezone(environ),
    )


def activities_from_environment(
    environ: Mapping[str, str],
    reviewers: ReviewersInForce,
    grader: GraderService | None = None,
    agent: DelegatedWorkService | None = None,
    forge: ConversingForge | None = None,
    judge: JudgeService | None = None,
    spend_relation: str = "journal",
) -> ReviewActivities:
    """Build the review activities for the reviewers in force.

    ``DATABASE_URL`` is required. ``grader``, ``agent``, ``forge`` and
    ``judge`` each replace what the settings would build: the grader of
    a write-up, the runner, the forges and the judge. ``spend_relation``
    names the table or view what was spent is read from.

    Without a forge's settings, an evaluation of a pull request on that
    forge fails with a reason that says so. Without a key for the
    judge, nothing is judged.

    Raises ``ValueError`` if a setting that is given cannot be used.
    """
    database_url = environ["DATABASE_URL"]
    agents = dict(reviewers.agents)
    layers = reviewers.layers
    named = agent.runner if agent else environ.get("REVIEW_RUNNER", "")
    dispatch, runner = reviewing_from_environment(
        environ,
        agents,
        # What the layer a delivery fires holds. A reviewer the topology
        # does not name there is not dispatched on a pull request.
        reviewers_on(layers, EVENT.name),
        # Every reviewer any layer holds, which says whether this worker
        # needs a runner at all.
        reviewers_anywhere(layers),
        agent,
    )
    forge = forge or forge_from_environment(environ)
    objects = object_store_from_environment(environ)
    judging = judging_agent(reviewers)
    return ReviewActivities(
        forge=forge,
        # The same forges answer for a closed conversation.
        conversation=forge,
        doctrine=reviewers.doctrine_of(judging) if judging else NoDoctrine(),
        judge=judge or judge_from_environment(environ, reviewers, objects),
        journal=review_journal(
            database_url, build_sha(environ), reviewers.deployed_from
        ),
        snapshots=SqlAlchemySnapshotStore(database_url),
        clock=SystemClock(),
        archive=SqlAlchemyJudgeArchive(database_url),
        write_ups=SqlAlchemyWriteUpArchive(database_url),
        enforcement=SqlAlchemyEnforcement(database_url),
        withholding=SqlAlchemyWithholding(database_url),
        boundaries=boundaries_from_environment(environ, reviewers),
        # What each installed reviewer answers for, which is what its
        # verdict covers.
        agents=verdict_scope(agents, answered_policies(reviewers)),
        # Each installed reviewer's own prose and pinned runner, which
        # its findings are stamped with. The judge's fingerprint is not
        # here: answering it can reach the proxy, and startup must not,
        # so the corpus asks for it when it loads.
        installed=corpus_of(
            agents,
            reviewers.prose,
            {runner.runner: runner.fingerprint} if runner else {},
        ),
        summaries=policy_summaries(reviewers.policies),
        reviewers=dispatch,
        # The reviewers of every layer on a clock, so a stocktake
        # dispatches what its own layer holds. By the runner that was
        # named, whether or not it could be built, so that a reviewer
        # that cannot be started is still named at startup.
        by_layer={
            name: dispatchable(
                agents,
                named,
                reviewers_on({name: layer}, layer.cadence.name),
                layer=name,
                worth=worth_on(layer),
            )
            for name, layer in layers.items()
            if layer.cadence.on_a_clock
        },
        # Read at each dispatch and not here, so a ceiling can be
        # lowered without a restart.
        ceilings=SqlAlchemySpendBindings(database_url),
        judged=SqlAlchemyJudgedPolicies(database_url),
        dispatched=SqlAlchemyDispatchedProcesses(database_url),
        processes={
            name: processes_on(layer) for name, layer in layers.items()
        },
        classes=policy_classes(reviewers),
        checked=checked_policies(agents),
        spend=SqlAlchemySpendRecord(database_url, spend_relation),
        agent=runner,
        grader=grader,
        governance=SqlAlchemyGovernance(
            database_url, governing_by_default(agents)
        ),
    )


def backfill_activities_from_environment(
    environ: Mapping[str, str],
    reviewers: ReviewersInForce,
    spend_relation: str = "journal",
) -> BackfillActivities:
    """Build the backfill's activities, listing closed pull requests
    from each forge whose settings are given. ``DATABASE_URL`` is
    required. ``spend_relation`` names the table or view what was spent
    is read from."""
    database_url = environ["DATABASE_URL"]
    feeds: dict[str, ClosedPullRequestFeedRepository] = {}
    token = forge_token(environ)
    if token:
        feeds["github"] = ForgeClosedPullRequests(GitHubForge(token))
    forgejo = forgejo_settings(environ)
    if forgejo:
        feeds["forgejo"] = ForgeClosedPullRequests(ForgejoForge(*forgejo))
    return BackfillActivities(
        feeds,
        WorkJournalQueries(database_url),
        SystemClock(),
        # What a backfill is allowed, and what has already been spent.
        # A backfill judges every pull request it reads, and judging
        # dispatches nobody, so the check made at a dispatch does not
        # cover it.
        SqlAlchemySpendBindings(database_url),
        SqlAlchemySpendRecord(database_url, spend_relation),
        boundaries_from_environment(environ, reviewers),
    )


def _warn(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def check_judging_models(
    judge: object,
    declared: Iterable[str] = (),
    warn: Callable[[str], None] = _warn,
) -> None:
    """Refuse a class of model that names a model the proxy does not
    publish, and a declared policy that has no model.

    The classes' models and the proxy's list of models are written from
    the same settings. This checks that they agree once, before any
    judging, so a mistyped model stops the worker and does not produce
    findings from the wrong one. A proxy that cannot be reached yet is
    not a mistyped model: that is said through ``warn`` and the worker
    starts.

    A class with no model is not a mistake, but a policy a reviewer
    declared and cannot have judged is. A reviewer's verdict covers
    what it declared, so a policy in ``declared`` whose class has no
    model stops the worker. Dropping the policy from the reviewer's
    manifest is how a deployment says it means to run without it. A
    policy that is skipped and not declared is named through ``warn``.

    Does nothing for a judge that is not the proxy's.

    Raises ``ValueError`` to stop the worker.
    """
    if not isinstance(judge, LiteLLMJudge):
        return
    try:
        judge.check_model_classes()
        skipped = judge.drop_unsupplied_policies()
    except JudgeTemporarilyUnavailableError as exc:
        warn(f"warning: the model classes are unchecked: {exc}")
        return
    except JudgeUnavailableError as exc:
        raise ValueError(str(exc)) from exc
    undeliverable = sorted(set(skipped) & set(declared))
    if undeliverable:
        one = len(undeliverable) == 1
        raise ValueError(
            f"{', '.join(undeliverable)} "
            + ("is" if one else "are")
            + " declared by an installed reviewer and "
            + ("needs" if one else "need")
            + " a class of model this server supplies none of. Supply one "
            "through the class's setting, or drop the policy from the "
            "reviewer's manifest."
        )
    if skipped:
        one = len(skipped) == 1
        warn(
            f"note: {', '.join(skipped)} "
            + ("needs" if one else "need")
            + " a class of model this server supplies none of, and "
            + ("is" if one else "are")
            + " not judged"
        )


def refuse_without_a_forge(
    environ: Mapping[str, str], enforcement: EnforcementProfileService
) -> None:
    """Stop a worker that would publish and has no forge to publish to.

    Without a forge's settings, each evaluation of a pull request fails
    with a reason that says so. If a repository is bound to a profile
    that publishes, that is every evaluation of it, each saying the
    same thing. This says it once, before any of them.

    A binding is a record and may change while the worker runs, so this
    holds for the moment the worker started. After that the failure of
    each evaluation is what says it.

    Raises ``ValueError`` if a repository is bound to a profile that
    publishes and neither forge's settings are given.
    """
    if forge_token(environ) or forgejo_settings(environ):
        return
    publishing = sorted(
        f"{forge}:{repo}"
        for (forge, repo), profile in enforcement.bindings().items()
        if profile.publishes
    )
    if publishing:
        raise ValueError(
            f"{', '.join(publishing)} is bound to a profile that "
            "publishes, and FORGE_TOKEN is not set, nor FORGEJO_URL "
            "and FORGEJO_TOKEN; the worker does not start without a "
            "forge to publish to"
        )


def _judging(judge: JudgeService | None) -> str:
    """Say which policies the judge answers, in a line for the log."""
    if judge is None:
        return "judges nothing: LITELLM_MASTER_KEY is not set"
    if not judge.policies:
        return "judges nothing: the deployment gives the judge no policy"
    return f"judges {', '.join(judge.policies)}"


def _say(line: str) -> None:
    print(line, flush=True)


def parts_from_environment(
    environ: Mapping[str, str],
    grader: GraderService | None = None,
    agent: DelegatedWorkService | None = None,
    *,
    forge: ConversingForge | None = None,
    judge: JudgeService | None = None,
    spend_relation: str = "journal",
) -> WorkerParts:
    """Build the part of a worker that reviews, from the settings this
    module's docstring lists and the deployment in force.

    ``grader`` grades a reviewer's write-up; with none, a write-up is
    kept and not graded. ``agent`` is the runner reviews are dispatched
    to; with none, the one ``REVIEW_RUNNER`` names. ``forge`` and
    ``judge`` replace the forges and the judge the settings would
    build. ``spend_relation`` names the table or view what was spent is
    read from, the journal unless a server keeps a view of its own.

    What comes back depends on what is installed:

    - No ``DATABASE_URL``: nothing but a line saying so.
    - No deployment in force: a watcher that stops the worker when one
      is put in force, and a line. No workflow is registered, and none
      of the refusals below is made.
    - A deployment in force: the review workflows, their activities on
      the three kinds of queue, the stocktake schedules, and a watcher
      that stops the worker when another deployment is put in force.

    With a deployment in force, three things are checked before the
    worker serves, and each stops it with a ``ValueError``:

    - a repository is bound to a profile that publishes and no forge's
      settings are given (not checked if ``forge`` is passed);
    - a repository ``WATCHED_REPOSITORIES`` names has declared no
      boundary for one of the deployment's layers;
    - a class of model names a model the proxy does not publish, or a
      policy a reviewer declared has no model.

    A missing forge token or judge key alone stops nothing: evaluations
    of that forge's pull requests fail one at a time, and nothing is
    judged.

    Raises ``ValueError`` if a setting that is given cannot be used or
    the deployment does not parse, and ``ReviewAgentError`` if
    ``REVIEW_AGENTS`` names a reviewer the deployment does not hold.
    """
    database_url = environ.get("DATABASE_URL", "")
    if not database_url:
        return WorkerParts(lines=("reviews nothing: DATABASE_URL is not set",))
    deployments = SqlAlchemyPolicyDeployments(database_url)
    reviewers = reviewers_in_force(
        deployments, checks_from(environ), reviewer_names(environ)
    )
    started_with = reviewers.deployed_from if reviewers else None

    async def watch(stop: asyncio.Event) -> None:
        await stop_on_new_deployment(
            stop.set, started_with, deployments, say=_say, stopping=stop
        )

    if reviewers is None:
        return WorkerParts(
            watchers=(watch,),
            lines=("reviews nothing: no policy deployment is in force",),
        )
    activities = activities_from_environment(
        environ, reviewers, grader, agent, forge, judge, spend_relation
    )
    backfill = backfill_activities_from_environment(
        environ, reviewers, spend_relation
    )
    layers = reviewers.layers
    watched = watched_repositories(environ)
    zone = periods_timezone(environ)
    boundaries = SqlAlchemyLayerBoundaries(database_url)

    async def schedule_stocktakes(client: Client, task_queue: str) -> None:
        # One schedule for each layer on a clock, for each watched
        # repository. Made here because the worker that has just read
        # the topology is what knows what it asks for.
        made = await reconcile(
            TemporalScheduler(client, STOCKTAKE_WORKFLOW),
            layers,
            watched,
            task_queue,
            boundaries,
            SystemClock().now(),
            zone,
        )
        if made:
            _say(f"stocktakes scheduled: {', '.join(made)}")

    def a_forge_to_publish_to() -> None:
        if forge is None:
            refuse_without_a_forge(
                environ, SqlAlchemyEnforcement(database_url)
            )

    def a_boundary_for_every_period() -> None:
        refuse_without_a_boundary(layers, watched, boundaries)

    def a_model_for_every_declared_policy() -> None:
        check_judging_models(
            activities.judge_port, declared_policies(reviewers)
        )

    came_from = reviewers.deployed_from
    return WorkerParts(
        workflows=WORKFLOWS,
        activities=(*activities.all(), *backfill.all()),
        judging=tuple(activities.judging()),
        assessing={
            name: tuple(activities.assessing())
            for name in MODEL_CLASS_VARIABLES
        },
        schedules=(schedule_stocktakes,),
        before_serving=(
            a_forge_to_publish_to,
            a_boundary_for_every_period,
            a_model_for_every_declared_policy,
        ),
        watchers=(watch,),
        lines=(
            f"reviews under {came_from.repository} at {came_from.commit}, "
            f"content {came_from.content_hash[:12]}",
            f"holds the layers {', '.join(layers)}"
            if layers
            else "holds no layer",
            _judging(activities.judge_port),
            activities.reviewing,
            activities.collecting,
        ),
    )
