"""The activities the review workflows call. Each calls one use case.

They also decide what Temporal may retry. A failure that may pass is
raised as an error Temporal retries, after the wait the forge asked for
if it asked for one. A failure that will not pass is raised as one
Temporal does not retry, so the evaluation fails at once.

An activity's name is what a recorded history holds, so the names here
do not change.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from tempfile import gettempdir
from typing import Any
from uuid import uuid4

from temporalio import activity
from temporalio.exceptions import ApplicationError

from bugflow.apps.worker.backfill import (
    LIST_BACKFILL_PAGE_ACTIVITY,
    OUT_OF_ROOM_ACTIVITY,
)
from bugflow.apps.worker.conversation import ForgeConversation
from bugflow.apps.worker.corpus import (
    ConfiguredCorpus,
    ConfiguredEvaluationRegime,
)
from bugflow.apps.worker.delegated_work import WorkDelegation
from bugflow.apps.worker.evaluate_pull_request import (
    ASSESS_ACTIVITY,
    CHECK_ACTIVITY,
    JUDGE_ACTIVITY,
    JUDGE_MAX_ATTEMPTS,
    JUDGE_POLICIES_ACTIVITY,
    OBSERVE_ACTIVITY,
    POLICIES_ACTIVITY,
    PUBLISH_ACTIVITY,
    REVIEW_AGENTS_ACTIVITY,
    REVIEW_COLLECT_ACTIVITY,
    REVIEW_DISPATCH_ACTIVITY,
    REVIEW_STOP_ACTIVITY,
    REVIEW_WAIT_ACTIVITY,
)
from bugflow.apps.worker.publication import ForgePublication
from bugflow.apps.worker.pull_request import (
    COLLECT_AT_CLOSE_ACTIVITY,
    IS_OPEN_ACTIVITY,
)
from bugflow.apps.worker.review_scope import DeclaredReviewScope
from bugflow.apps.worker.reviewers import (
    Boundaries,
    ReviewerSettings,
    allowance_for,
    judging_over_ceiling,
    policies_for,
    refused_by,
    reviewers_for,
)
from bugflow.apps.worker.reviewers import out_of_room as what_is_left
from bugflow.apps.worker.stocktake import (
    STOCKTAKE_COLLECT_ACTIVITY,
    STOCKTAKE_DISPATCH_ACTIVITY,
    STOCKTAKE_GRADE_ACTIVITY,
    STOCKTAKE_REVIEWERS_ACTIVITY,
    STOCKTAKE_WAIT_ACTIVITY,
    TAKE_STOCK_ACTIVITY,
)
from bugflow.apps.worker.submission_source import ForgeSubmissionSource
from bugflow.apps.worker.worktree import WorkWorktrees
from bugflow.forge.domain.errors import (
    ForgeError,
    ForgeRejectedError,
    ForgeUnavailableError,
    SnapshotNotFoundError,
)
from bugflow.forge.domain.repositories.snapshots import SnapshotStoreRepository
from bugflow.forge.domain.services.conversation import (
    ConversationService as ForgeConversationService,
)
from bugflow.forge.domain.services.forge import ForgeService
from bugflow.forge.dtos.observe_pull_request import (
    ObservePullRequestRequest,
    ObservePullRequestResponse,
)
from bugflow.forge.usecases.observe_pull_request import (
    ObservePullRequestUseCase,
)
from bugflow.method.domain.models.corpus import AgentCorpus
from bugflow.method.domain.repositories.doctrine import DoctrineRepository
from bugflow.review.domain.errors import JudgeTemporarilyUnavailableError
from bugflow.review.domain.models.delegation import Handle, Run
from bugflow.review.domain.models.evaluation import Answerable
from bugflow.review.domain.repositories.judge_archive import (
    JudgeArchiveRepository,
)
from bugflow.review.domain.repositories.write_up_archive import (
    WriteUpArchiveRepository,
)
from bugflow.review.domain.services.enforcement import (
    EnforcementProfileService,
)
from bugflow.review.domain.services.governance import GovernanceService
from bugflow.review.domain.services.grader import GraderService
from bugflow.review.domain.services.journal import JournalService
from bugflow.review.domain.services.judge import JudgeService
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
from bugflow.review.domain.services.withholding import WithholdingService
from bugflow.review.dtos.assess_policy import (
    AssessPolicyRequest,
    AssessPolicyResponse,
)
from bugflow.review.dtos.check_pull_request import (
    CheckPullRequestRequest,
    CheckPullRequestResponse,
)
from bugflow.review.dtos.collect_at_close import (
    CollectAtCloseRequest,
    CollectAtCloseResponse,
)
from bugflow.review.dtos.collect_review import CollectReviewRequest
from bugflow.review.dtos.dispatch_review import DispatchReviewRequest
from bugflow.review.dtos.grade_review import (
    GradeReviewRequest,
    GradeReviewResponse,
)
from bugflow.review.dtos.judge_pull_request import (
    JudgePullRequestRequest,
    JudgePullRequestResponse,
)
from bugflow.review.dtos.publish_findings import (
    PublishFindingsRequest,
    PublishFindingsResponse,
)
from bugflow.review.dtos.review_range import (
    CollectRangeReviewRequest,
    CollectRangeReviewResponse,
    DispatchRangeReviewRequest,
    DispatchRangeReviewResponse,
    GradeRangeReviewRequest,
    GradeRangeReviewResponse,
    WaitRangeReviewRequest,
    WaitRangeReviewResponse,
)
from bugflow.review.dtos.review_with_agent import (
    DispatchedReview,
    ReviewAgentActivityRequest,
    ReviewAgentActivityResponse,
    ReviewCollectActivityRequest,
)
from bugflow.review.dtos.take_stock import TakeStockRequest, TakeStockResponse
from bugflow.review.dtos.wait_review import (
    WaitReviewRequest,
    WaitReviewResponse,
)
from bugflow.review.infrastructure.declared_enforcement import (
    DeclaredEnforcement,
)
from bugflow.review.infrastructure.in_memory_enforcement import (
    InMemoryEnforcement,
)
from bugflow.review.infrastructure.ungraded_write_ups import UngradedWriteUps
from bugflow.review.usecases.check_pull_request import CheckPullRequestUseCase
from bugflow.review.usecases.collect_at_close import CollectAtCloseUseCase
from bugflow.review.usecases.collect_review import CollectReviewUseCase
from bugflow.review.usecases.dispatch_review import DispatchReviewUseCase
from bugflow.review.usecases.grade_review import GradeReviewUseCase
from bugflow.review.usecases.judge_pull_request import JudgePullRequestUseCase
from bugflow.review.usecases.publish_findings import PublishFindingsUseCase
from bugflow.review.usecases.review_range import (
    CollectRangeReviewUseCase,
    DispatchRangeReviewUseCase,
    GradeRangeReviewUseCase,
    WaitRangeReviewUseCase,
)
from bugflow.review.usecases.take_stock import TakeStockUseCase
from bugflow.review.usecases.wait_review import WaitReviewUseCase
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.work.domain.models.backfill import WatchedRepository
from bugflow.work.domain.repositories.backfill import (
    ClosedPullRequestFeedRepository,
)
from bugflow.work.domain.services.delegated_work import (
    DelegatedWorkService as WorkDelegatedWorkService,
)
from bugflow.work.domain.services.journal import (
    JournalService as WorkJournalService,
)
from bugflow.work.domain.services.worktree import (
    WorktreeService as WorkWorktreeService,
)
from bugflow.work.dtos.list_backfill_page import (
    ListBackfillPageRequest,
    ListBackfillPageResponse,
)
from bugflow.work.usecases.list_backfill_page import ListBackfillPageUseCase


@dataclass(frozen=True)
class _Review:
    """A review's four use cases, and the runner a stop is asked of."""

    agent: WorkDelegation
    dispatch: DispatchReviewUseCase
    wait: WaitReviewUseCase
    collect: CollectReviewUseCase
    grade: GradeReviewUseCase


def _as_activity_response(
    run: Run | None, reason: str, graded: GradeReviewResponse | None = None
) -> ReviewAgentActivityResponse:
    """Return what the workflow needs from a review, and no more."""
    return ReviewAgentActivityResponse(
        verdict=graded.verdict if graded else None,
        reason=graded.reason if graded else reason,
        cost=run.cost if run else {},
        note=graded.note if graded else None,
        running=run is not None and run.outcome == "running",
    )


def _non_retryable(exc: Exception) -> ApplicationError:
    return ApplicationError(
        str(exc), type=type(exc).__name__, non_retryable=True
    )


def _retryable(
    exc: Exception, delay: timedelta | None = None
) -> ApplicationError:
    return ApplicationError(
        str(exc), type=type(exc).__name__, next_retry_delay=delay
    )


@dataclass(frozen=True)
class Checked:
    """A policy that a check answers, as a reviewer's manifest gives it
    on its ``checks`` line."""

    #: The reviewer whose policy it is.
    agent_id: str
    #: The id of the doctrine clause the check's findings cite.
    clause: str


def _as_check(
    request: AssessPolicyRequest, policy_id: str, checked: Checked
) -> CheckPullRequestRequest:
    """Build a checked policy's request from the one the caller sent.

    The policy's id, its clause and its reviewer are the manifest's.
    The corpus carries that reviewer's own version, so a caller that
    names a policy need not name the rest.
    """
    return CheckPullRequestRequest(
        snapshot=request.snapshot,
        policy_id=policy_id,
        clause=checked.clause,
        corpus_version=request.corpus.version_for(checked.agent_id),
        agent_id=checked.agent_id,
        correlation=request.correlation,
    )


def _as_judgement(request: AssessPolicyRequest) -> JudgePullRequestRequest:
    return JudgePullRequestRequest(
        snapshot=request.snapshot,
        corpus=request.corpus,
        correlation=request.correlation,
        use_judge=request.use_judge,
        policy_id=request.policy_id,
        head_sha=request.head_sha,
    )


def _as_assessed(
    answered: CheckPullRequestResponse | JudgePullRequestResponse,
) -> AssessPolicyResponse:
    """Return what came back, in the shape that names no method."""
    return AssessPolicyResponse(
        findings=answered.findings,
        status=answered.status,
        unavailable=getattr(answered, "unavailable", ()),
        answered=answered.answered,
    )


class ReviewActivities:
    """The activities of an evaluation, of a pull request's close and of
    a stocktake."""

    def __init__(
        self,
        forge: ForgeService,
        doctrine: DoctrineRepository,
        judge: JudgeService | None,
        journal: JournalService,
        snapshots: SnapshotStoreRepository,
        clock: ClockService,
        archive: JudgeArchiveRepository,
        # Where a checkout reviewer's write-up is stored. None if
        # nothing is set up to store it.
        write_ups: WriteUpArchiveRepository | None = None,
        enforcement: EnforcementProfileService | None = None,
        # What share of each repository's warnings is withheld. None,
        # and none is.
        withholding: WithholdingService | None = None,
        # What the forge says of a closed conversation. None if nothing
        # set up can say, and then collecting at close fails for good.
        conversation: ForgeConversationService | None = None,
        agents: Mapping[str, tuple[str, ...]] | None = None,
        governance: GovernanceService | None = None,
        summaries: Mapping[str, str] | None = None,
        reviewers: Mapping[str, ReviewerSettings] | None = None,
        worktrees: WorkWorktreeService | None = None,
        # The runner a review is dispatched to. None, and no review is
        # dispatched.
        agent: WorkDelegatedWorkService | None = None,
        # What grades a write-up. None, and a write-up is kept and not
        # graded.
        grader: GraderService | None = None,
        # Each installed reviewer's own prose and pinned runner, which
        # its findings are stamped with. Empty if no reviewer is
        # installed, and then a finding carries the evaluation's
        # version.
        installed: tuple[AgentCorpus, ...] = (),
        # The reviewers each layer on a clock holds, by layer name. A
        # reviewer no layer names runs nowhere.
        by_layer: Mapping[str, Mapping[str, ReviewerSettings]] | None = None,
        # What this deployment bound a run to spend, read at each
        # dispatch. None if nothing is set up, and then nothing allows
        # a dispatch to spend.
        ceilings: SpendBindingsService | None = None,
        # What has already been spent, which is what an allowance over
        # a period asks about.
        spend: SpendRecordService | None = None,
        # Where the periods an allowance is counted over begin.
        boundaries: Boundaries | None = None,
        # What each repository declared it is judged on. None if no
        # declarations are set up, and then the worker's own set is
        # used.
        judged: JudgedPoliciesService | None = None,
        # What each repository declared it dispatches, and which
        # process names each of a layer's reviewers, since a
        # declaration names processes and a fan-out names reviewers.
        dispatched: DispatchedProcessesService | None = None,
        processes: Mapping[str, Mapping[str, str]] | None = None,
        # The class of model each judged policy costs, which decides
        # the queue its answer runs on. A policy absent from it is
        # answered without a model.
        classes: Mapping[str, str] | None = None,
        # The policies a check answers, by policy id, as the reviewers'
        # manifests give them. A policy in it is answered by code and
        # needs no model.
        checked: Mapping[str, Checked] | None = None,
    ) -> None:
        # The judge itself, not the activity that calls it. Startup
        # asks it which policies have no model and drops them. The
        # fan-out and the observation's record of what was asked for
        # read the narrowed set, so the three must be the same object.
        self.judge_port = judge
        self._judged = judged
        self._checked = dict(checked or {})
        self._observe = ObservePullRequestUseCase(
            forge,
            ConfiguredEvaluationRegime(
                ConfiguredCorpus(doctrine, judge, installed)
            ),
            snapshots,
            journal,
            journal,
            clock,
            # What the observation records it was scoped to, so that a
            # policy switched off for the repository is visible.
            DeclaredReviewScope(self._answerable(), judged),
        )
        submissions = ForgeSubmissionSource(snapshots)
        self._judge = JudgePullRequestUseCase(
            judge, submissions, journal, clock, archive
        )
        self._check = CheckPullRequestUseCase(submissions, journal, clock)
        # The reviewers this worker can dispatch, by id, each with the
        # prose its manifest carries and what a run of it may spend.
        # Empty if nothing is set up to run one, and then nothing is
        # fanned out.
        self._reviewers = dict(reviewers or {})
        self._ceilings = ceilings
        self._spend = spend
        # A deployment that declares no boundary has no allowance over
        # a period, which is what an empty topology amounts to.
        self._boundaries = boundaries or Boundaries(layers={})
        self._dispatched = dispatched
        self._classes = dict(classes or {})
        self._processes = {
            layer: dict(named) for layer, named in (processes or {}).items()
        }
        self._clock = clock
        self._by_layer = {
            layer: dict(held) for layer, held in (by_layer or {}).items()
        }
        # None if no runner is set up, and then no review is
        # dispatched. A worktree is optional: a runner that fetches the
        # repository itself is given none.
        self._review: _Review | None = None
        self._stocktake_dispatch: DispatchRangeReviewUseCase | None = None
        self._stocktake_wait: WaitRangeReviewUseCase | None = None
        self._stocktake_collect: CollectRangeReviewUseCase | None = None
        self._stocktake_grade: GradeRangeReviewUseCase | None = None
        if agent is not None:
            grading = grader or UngradedWriteUps()
            delegation = WorkDelegation(agent)
            self._review = _Review(
                agent=delegation,
                dispatch=DispatchReviewUseCase(
                    WorkWorktrees(worktrees)
                    if worktrees is not None
                    else None,
                    delegation,
                    journal,
                    clock,
                ),
                wait=WaitReviewUseCase(delegation),
                collect=CollectReviewUseCase(
                    delegation, journal, clock, write_ups
                ),
                grade=GradeReviewUseCase(grading, journal, clock),
            )
            # A stocktake's own four steps, over the same runner and
            # grader: a range is not a commit and its facts are its
            # own.
            self._stocktake_dispatch = DispatchRangeReviewUseCase(
                delegation, journal, clock
            )
            self._stocktake_wait = WaitRangeReviewUseCase(delegation)
            self._stocktake_collect = CollectRangeReviewUseCase(
                delegation, journal, clock
            )
            self._stocktake_grade = GradeRangeReviewUseCase(
                grading, journal, clock
            )
        self._collect = (
            CollectAtCloseUseCase(
                journal, ForgeConversation(conversation), clock
            )
            if conversation is not None
            else None
        )
        # What a layer takes stock of. It reads the journal and nothing
        # else, so it needs no forge and no runner: a stocktake of a
        # quiet period costs nothing.
        self._take_stock = TakeStockUseCase(journal, clock)
        self._publish = PublishFindingsUseCase(
            ForgePublication(forge),
            journal,
            clock,
            enforcement=DeclaredEnforcement(
                enforcement or InMemoryEnforcement(), withholding
            ),
            agents=agents,
            governance=governance,
            summaries=summaries,
            submissions=submissions,
        )
        # Asked directly and not through a use case: whether a pull
        # request is still open is one call to the forge with no
        # decision in it.
        self._forge = forge

    @activity.defn(name=OBSERVE_ACTIVITY)
    def observe(
        self, request: ObservePullRequestRequest
    ) -> ObservePullRequestResponse:
        # What this repository is judged on, so that a text judged
        # before is judged again when a policy has been added to it
        # since, which the corpus version does not carry. Filled in
        # here and not by the workflow: reading it in the workflow
        # would be another command in every history. Judged policies
        # only, because a checked policy records no snapshot to match
        # and so can never be counted as answered.
        ref = request.ref
        request = request.model_copy(
            update={
                "declared": tuple(
                    self.judge_policies(ref.forge, f"{ref.owner}/{ref.repo}")
                )
            }
        )
        try:
            return self._observe.execute(request)
        except ForgeUnavailableError as exc:
            raise _retryable(exc, exc.retry_after) from exc
        except ForgeError as exc:
            raise _non_retryable(exc) from exc

    @property
    def collecting(self) -> str:
        """Whether this worker reads a closed pull request's
        conversation, in a line for the log. A close that is never read
        fails nothing but its own activity, so nothing else would say
        it."""
        if self._collect is None:
            return "not collecting at close: no forge can read a conversation"
        return "collecting conversations at close"

    @property
    def reviewing(self) -> str:
        """Which reviewers this worker dispatches, in a line for the
        log.

        The line says what a pull request starts and what each layer on
        a clock starts. A reviewer that is held and cannot be started,
        because no runner is set up, is named with that reason. Nothing
        else reports a review that is never started, because it fails
        nothing.
        """
        on_a_clock = {
            layer: sorted(held)
            for layer, held in sorted(self._by_layer.items())
            if held
        }
        if self._review is None:
            held = sorted(set(self._reviewers).union(*on_a_clock.values()))
            if held:
                return (
                    "starts no review agent: "
                    + ", ".join(held)
                    + " cannot be started, because the runner is not"
                    " configured"
                )
            return "starts no review agent: none is configured"
        on_a_pull_request = (
            "starts " + ", ".join(sorted(self._reviewers))
            if self._reviewers
            else "starts no review agent"
        ) + " on a pull request"
        if not on_a_clock:
            return on_a_pull_request + "; no layer on a clock starts one"
        return "; ".join(
            [on_a_pull_request]
            + [
                f"{layer} layer starts {', '.join(held)}"
                for layer, held in on_a_clock.items()
            ]
        )

    @activity.defn(name=REVIEW_AGENTS_ACTIVITY)
    def review_agents(self) -> list[str]:
        """Return the reviewers this worker can dispatch, for the
        workflow to fan out.

        Nothing is called: the workflow needs the list before it can
        ask for a review from each. Empty if no runner is set up, and
        an empty fan-out is the answer and not a failed activity.
        """
        return sorted(self._reviewers) if self._review is not None else []

    @activity.defn(name=STOCKTAKE_REVIEWERS_ACTIVITY)
    def stocktake_reviewers(
        self, layer: str, forge: str = "", repo: str = ""
    ) -> list[str]:
        """Return the reviewers to run for that repository at that
        layer.

        Empty if the layer holds none, if no runner is set up, and if
        the repository declared none of the layer's processes. A
        request that names no repository runs the whole layer.
        """
        if self._review is None:
            return []
        held = sorted(self._by_layer.get(layer, {}))
        if not repo:
            return held
        return reviewers_for(
            held,
            self._dispatched,
            self._processes.get(layer, {}),
            forge,
            repo,
        )

    @activity.defn(name=STOCKTAKE_DISPATCH_ACTIVITY)
    def stocktake_dispatch(
        self, request: DispatchRangeReviewRequest
    ) -> DispatchRangeReviewResponse:
        """Start a review of the range, and return its handle."""
        if self._stocktake_dispatch is None:
            return DispatchRangeReviewResponse(
                handle=None, reason="no runner is configured"
            )
        settings = self._by_layer.get(request.layer, {}).get(request.agent_id)
        if settings is None:
            # The one refusal nothing can record: without settings there
            # is no reviewer to record it against.
            return DispatchRangeReviewResponse(
                handle=None,
                reason=(
                    f"{request.layer} holds no reviewer "
                    f"called {request.agent_id}"
                ),
            )
        refusal = refused_by(
            self._ceilings,
            self._spend,
            self._boundaries,
            self._clock.now(),
            request.forge,
            request.repo,
            settings,
        )
        allowed = allowance_for(
            self._ceilings, request.forge, request.repo, settings
        )
        if refusal is None and allowed is None:
            refusal = (
                f"nothing allows {request.agent_id} to spend on "
                f"{request.repo} at {request.layer}"
            )
        # Through the use case either way, so a refusal is recorded
        # where a dispatch is and a reader finds both in one place.
        return self._stocktake_dispatch.execute(
            request.model_copy(
                update={
                    "instructions": settings.instructions,
                    "budget": allowed,
                    "refusal": refusal or "",
                }
            )
        )

    @activity.defn(name=STOCKTAKE_WAIT_ACTIVITY)
    def stocktake_wait(
        self, request: WaitRangeReviewRequest
    ) -> WaitRangeReviewResponse:
        """Wait for the range's review to have something to read, or
        hand the activity over to whoever will be told."""
        if self._stocktake_wait is None or self._review is None:
            return WaitRangeReviewResponse(ready=False)
        if self._review.agent.notifies:
            activity.raise_complete_async()
        return self._stocktake_wait.execute(request)

    @activity.defn(name=STOCKTAKE_COLLECT_ACTIVITY)
    def stocktake_collect(
        self, request: CollectRangeReviewRequest
    ) -> CollectRangeReviewResponse:
        """Read what the range's review produced, and what it cost."""
        if self._stocktake_collect is None:
            return CollectRangeReviewResponse(
                run=None, reason="no runner is configured"
            )
        return self._stocktake_collect.execute(request)

    @activity.defn(name=STOCKTAKE_GRADE_ACTIVITY)
    def stocktake_grade(
        self, request: GradeRangeReviewRequest
    ) -> GradeRangeReviewResponse:
        """Return what grading made of the range's write-up."""
        if self._stocktake_grade is None:
            return GradeRangeReviewResponse(
                status=None, detail="no runner is configured"
            )
        return self._stocktake_grade.execute(request)

    def _worktree_for(self, request: ReviewAgentActivityRequest) -> Path:
        """Name the directory a runner that reads one is given.

        A name and not a directory: a worktree service creates it when
        it prepares one, and a runner that fetches the repository itself
        is given no worktree and never looks.
        """
        return Path(gettempdir()) / f"bugflow-review-{uuid4().hex}"

    def _settings_for(self, agent_id: str) -> ReviewerSettings | None:
        return self._reviewers.get(agent_id) if self._review else None

    def _request_for(
        self, request: ReviewAgentActivityRequest, worktree: Path
    ) -> DispatchReviewRequest | None:
        """Build what to ask of the dispatch, or return None if this
        reviewer is not this worker's to run.

        A request carrying a refusal is still a request: the use case
        records why nothing ran, which is how a review refused for money
        is told from a reviewer nobody installed.
        """
        settings = self._settings_for(request.agent_id)
        if settings is None:
            return None
        repo = f"{request.ref.owner}/{request.ref.repo}"
        refusal = refused_by(
            self._ceilings,
            self._spend,
            self._boundaries,
            self._clock.now(),
            request.ref.forge,
            repo,
            settings,
        )
        allowed = allowance_for(
            self._ceilings, request.ref.forge, repo, settings
        )
        if refusal is None and allowed is None:
            refusal = f"nothing allows {request.agent_id} to spend on {repo}"
        return DispatchReviewRequest(
            refusal=refusal or "",
            ref=request.ref,
            head_sha=request.head_sha,
            base_sha=request.base_sha,
            agent_id=request.agent_id,
            corpus_version=request.corpus_version,
            instructions=settings.instructions,
            worktree=worktree,
            budget=allowed,
            correlation=request.correlation,
        )

    @activity.defn(name=REVIEW_DISPATCH_ACTIVITY)
    def review_dispatch(
        self, request: ReviewAgentActivityRequest
    ) -> DispatchedReview:
        """Start the run and return its handle, without waiting for it.

        A run outlives this call. The workflow holds the handle and
        waits with a deadline of its own, and nothing is kept in this
        process between steps.
        """
        if self._review is None:
            return DispatchedReview(reason="no runner is configured")
        asked = self._request_for(request, self._worktree_for(request))
        if asked is None:
            return DispatchedReview(
                reason=f"{request.agent_id} is not installed here"
            )
        dispatched = self._review.dispatch.execute(asked)
        return DispatchedReview(
            handle=dispatched.handle,
            withheld=dispatched.withheld,
            reason=dispatched.reason,
            reused=dispatched.reused,
        )

    @activity.defn(name=REVIEW_WAIT_ACTIVITY)
    def review_wait(self, request: WaitReviewRequest) -> WaitReviewResponse:
        """Wait for the run to have something to read.

        The waiting is the runner's adapter's, and it is done in this
        activity and not in the workflow.

        A runner whose completions reach this server by a route of their
        own is not waited on at all: the activity is handed over and
        whoever receives the completion ends it, which occupies no
        worker while a run lasts. The activity's schedule-to-close
        timeout is the patience, so a completion that never comes still
        ends the wait.
        """
        if self._review is None:
            return WaitReviewResponse(ready=False)
        if self._review.agent.notifies:
            activity.raise_complete_async()
        return self._review.wait.execute(request)

    @activity.defn(name=REVIEW_STOP_ACTIVITY)
    def review_stop(self, handle: Handle) -> None:
        """End a run that outstayed its deadline, so nothing runs on."""
        # Asked of the runner directly and not through a use case:
        # stopping is one call with no decision in it.
        if self._review is not None:
            self._review.agent.stop(handle)

    @activity.defn(name=REVIEW_COLLECT_ACTIVITY)
    def review_collect(
        self, request: ReviewCollectActivityRequest
    ) -> ReviewAgentActivityResponse:
        """Read what the run produced, and grade it.

        Two steps in one activity repeat the reading if a grading fails,
        which is cheap, and repeat nothing expensive: the run is over by
        now.
        """
        if self._review is None:
            return ReviewAgentActivityResponse(
                reason="no runner is configured"
            )
        review = request.review
        if self._settings_for(review.agent_id) is None:
            return ReviewAgentActivityResponse(
                reason=f"{review.agent_id} is not installed here"
            )
        collected = self._review.collect.execute(
            CollectReviewRequest(
                ref=review.ref,
                head_sha=review.head_sha,
                agent_id=review.agent_id,
                corpus_version=review.corpus_version,
                correlation=review.correlation,
                handle=request.handle,
            )
        )
        if collected.run is None or collected.reason:
            return _as_activity_response(collected.run, collected.reason)
        graded = self._review.grade.execute(
            GradeReviewRequest(
                ref=review.ref,
                head_sha=review.head_sha,
                agent_id=review.agent_id,
                corpus_version=review.corpus_version,
                correlation=review.correlation,
                run=collected.run,
            )
        )
        return _as_activity_response(collected.run, "", graded)

    @activity.defn(name=JUDGE_POLICIES_ACTIVITY)
    def judge_policies(self, forge: str, repo: str) -> list[str]:
        """Return the policies to judge for that repository, for the
        workflow to fan out.

        No model is called: the workflow needs the list before it can
        ask for a judgement on each.

        Read from the judge and not copied when this was built, so that
        a policy dropped at startup for want of a model is not fanned
        out to and then reported as a judge that could not answer.

        Narrowed to what the repository declared it is judged on. A
        repository that declared nothing is judged on nothing. A policy
        it declared that this worker has no judge for is not fanned out
        to either.
        """
        held = list(self.judge_port.policies) if self.judge_port else []
        return policies_for(held, self._judged, forge, repo)

    def _answerable(self) -> list[str]:
        """Return every policy this worker can answer, judged or
        checked.

        Read from the judge and not copied when this was built, so a
        policy dropped at startup for want of a model is not offered.
        """
        judged = list(self.judge_port.policies) if self.judge_port else []
        return judged + [
            policy_id
            for policy_id in sorted(self._checked)
            if policy_id not in judged
        ]

    @activity.defn(name=POLICIES_ACTIVITY)
    def review_policies(self, forge: str, repo: str) -> list[Answerable]:
        """Return what that repository is reviewed for, for the workflow
        to ask for one at a time.

        Nothing is answered here: the workflow needs the list before it
        can ask. Each policy carries the class of model its answer
        costs, because the workflow names a task queue and there is one
        queue for each class. It carries nothing about how the answer
        is reached.

        Narrowed to what the repository declared. A repository that
        declared nothing is reviewed for nothing. A policy it declared
        that this worker cannot answer is left out.
        """
        return [
            Answerable(
                policy_id=policy_id,
                model_class=self._classes.get(policy_id, ""),
            )
            for policy_id in policies_for(
                self._answerable(), self._judged, forge, repo
            )
        ]

    @activity.defn(name=ASSESS_ACTIVITY)
    def assess_policy(
        self, request: AssessPolicyRequest
    ) -> AssessPolicyResponse:
        """Answer one policy, by whatever answers it.

        The caller named a policy and this decides the method. A policy
        a reviewer's manifest gives to a check is settled by code and
        needs no model. Every other policy goes to the judge.
        """
        checked = self._checked.get(request.policy_id or "")
        if request.policy_id and checked is not None:
            return _as_assessed(
                self.check(_as_check(request, request.policy_id, checked))
            )
        return _as_assessed(self.judge(_as_judgement(request)))

    @activity.defn(name=JUDGE_ACTIVITY)
    def judge(
        self, request: JudgePullRequestRequest
    ) -> JudgePullRequestResponse:
        ref = request.snapshot.ref
        spent = judging_over_ceiling(
            self._ceilings,
            self._spend,
            request.correlation.run_id,
            ref.forge,
            f"{ref.owner}/{ref.repo}",
        )
        if spent is not None:
            # Unavailable and not answered: a policy that did not run
            # withdraws nothing, and reading it as one that found
            # nothing would retract what the last evaluation raised.
            # The money is the reason and it is said.
            return JudgePullRequestResponse(
                findings=(),
                status=spent,
                unavailable=(request.policy_id,) if request.policy_id else (),
            )
        final_attempt = activity.info().attempt >= JUDGE_MAX_ATTEMPTS
        try:
            return self._judge.execute(
                request.model_copy(update={"final_attempt": final_attempt})
            )
        except JudgeTemporarilyUnavailableError as exc:
            raise _retryable(exc, exc.retry_after) from exc
        except SnapshotNotFoundError as exc:
            raise _non_retryable(exc) from exc

    @activity.defn(name=IS_OPEN_ACTIVITY)
    def is_open(self, ref: PullRequestRef) -> bool:
        try:
            return self._forge.is_open(ref)
        except ForgeUnavailableError as exc:
            raise _retryable(exc, exc.retry_after) from exc
        except ForgeRejectedError:
            # The forge will not give us the pull request, and asking
            # again will not change that. Treat it as closed: a workflow
            # for a pull request nobody can read is one nothing will
            # ever end.
            return False
        except ForgeError as exc:
            raise _non_retryable(exc) from exc

    @activity.defn(name=CHECK_ACTIVITY)
    def check(
        self, request: CheckPullRequestRequest
    ) -> CheckPullRequestResponse:
        """Answer a policy with a check: no model, so nothing to be
        unavailable."""
        try:
            return self._check.execute(request)
        except SnapshotNotFoundError as exc:
            raise _non_retryable(exc) from exc

    @activity.defn(name=PUBLISH_ACTIVITY)
    def publish(
        self, request: PublishFindingsRequest
    ) -> PublishFindingsResponse:
        try:
            return self._publish.execute(request)
        except ForgeUnavailableError as exc:
            raise _retryable(exc, exc.retry_after) from exc
        except ForgeError as exc:
            raise _non_retryable(exc) from exc

    @activity.defn(name=TAKE_STOCK_ACTIVITY)
    def take_stock(self, request: TakeStockRequest) -> TakeStockResponse:
        """Return the range a layer has not taken stock of, and record
        the mark that says it has now."""
        return self._take_stock.execute(request)

    @activity.defn(name=COLLECT_AT_CLOSE_ACTIVITY)
    def collect_at_close(
        self, request: CollectAtCloseRequest
    ) -> CollectAtCloseResponse:
        """Read the conversation of a pull request that has closed,
        once. Reactions are not delivered, so this is when to look."""
        if self._collect is None:
            raise _non_retryable(
                RuntimeError("no forge is configured to read a conversation")
            )
        try:
            return self._collect.execute(request)
        except ForgeUnavailableError as exc:
            raise _retryable(exc, exc.retry_after) from exc
        except ForgeError as exc:
            raise _non_retryable(exc) from exc

    def all(self) -> list[Callable[..., Any]]:
        """Return every activity the task queue serves: all but the
        ones that call a model, which have queues of their own."""
        return [
            self.observe,
            self.judge_policies,
            self.review_policies,
            self.assess_policy,
            self.review_agents,
            self.check,
            self.publish,
            self.is_open,
            self.collect_at_close,
            self.take_stock,
            self.stocktake_reviewers,
            self.stocktake_dispatch,
            self.stocktake_wait,
            self.stocktake_collect,
            # Waiting spends no model money and holds its slot for as
            # long as the run lasts, so it is served here and not on
            # the rate-limited queue.
            self.review_wait,
            self.stocktake_grade,
        ]

    def judging(self) -> list[Callable[..., Any]]:
        """Return the activities the rate-limited queue serves.

        A review belongs there as well as a judgement. It is the most
        expensive thing this server does, and the rate limit that
        protects a quota holds across every worker and not for each
        process.
        """
        return [
            self.judge,
            # A run that started before there was a queue for each
            # class of model still sends its answers here.
            self.assess_policy,
            self.review_dispatch,
            self.review_stop,
            self.review_collect,
        ]

    def assessing(self) -> list[Callable[..., Any]]:
        """Return what one class of model's queue serves.

        One activity: a policy is asked for by name and this decides
        how it is answered. It is registered on the task queue too, for
        a policy answered without a model.
        """
        return [self.assess_policy]


class BackfillActivities:
    """The activities of a backfill."""

    def __init__(
        self,
        feeds: Mapping[str, ClosedPullRequestFeedRepository],
        journal: WorkJournalService,
        clock: ClockService,
        ceilings: SpendBindingsService | None = None,
        spend: SpendRecordService | None = None,
        boundaries: Boundaries | None = None,
    ) -> None:
        self._list = ListBackfillPageUseCase(feeds, journal)
        self._clock = clock
        self._ceilings = ceilings
        self._spend = spend
        # A deployment that declares no boundary has no allowance over
        # a period, which is what an empty topology amounts to.
        self._boundaries = boundaries or Boundaries(layers={})

    @activity.defn(name=OUT_OF_ROOM_ACTIVITY)
    def out_of_room(self, repository: str) -> str:
        """Say which allowance covering this repository has none left.

        Empty if every one of them has room, and if nothing is set up
        to answer. A backfill judges every pull request it reads, and
        judging dispatches nobody, so the check made at a dispatch does
        not cover it.
        """
        watched = WatchedRepository.parse(repository)
        return (
            what_is_left(
                self._ceilings,
                self._spend,
                self._boundaries,
                self._clock.now(),
                watched.forge,
                f"{watched.owner}/{watched.repo}",
            )
            or ""
        )

    @activity.defn(name=LIST_BACKFILL_PAGE_ACTIVITY)
    def list_page(
        self, request: ListBackfillPageRequest
    ) -> ListBackfillPageResponse:
        try:
            return self._list.execute(request)
        except ForgeUnavailableError as exc:
            raise _retryable(exc, exc.retry_after) from exc
        except (ForgeError, ValueError) as exc:
            raise _non_retryable(exc) from exc

    def all(self) -> list[Callable[..., Any]]:
        return [self.list_page, self.out_of_room]
