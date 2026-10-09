"""Evaluate one pull request, from reading it to publishing.

This use case decides the order of an evaluation's steps: which run
side by side, which are skipped, and what happens when a review fails.
Each step is called through an interface, and behind most of them an
application runs another use case.

In a worker this use case runs inside a workflow, and each step it
waits for is scheduled by the workflow engine. The engine replays an
evaluation by repeating its steps in the order they were started. So a
change that adds, removes or reorders a step here changes the workflow,
and must be made as ``ExecutionService`` describes. The use case imports
nothing from the workflow engine.
"""

import asyncio

from bugflow.review.domain.errors import ReviewIncompleteError
from bugflow.review.domain.models.evaluation import (
    Answerable,
    Assessed,
    Observation,
    Publication,
    ReviewAsked,
    Reviewed,
)
from bugflow.review.domain.services.evaluation import (
    AgentReviewService,
    AssessmentService,
    ExecutionService,
    ObservationService,
    PublishingService,
)
from bugflow.review.dtos.evaluate_pull_request import (
    EvaluatePullRequestRequest,
    EvaluatePullRequestResponse,
)
from bugflow.review.usecases.publish_findings import cited_clauses
from bugflow.shared.domain.values.correlation import Correlation

#: The id of a change to the steps: a policy is asked about by its id,
#: where before a checking step and a judging step were called in turn.
#: No run is left that takes the old steps, so the old steps are gone
#: and the use case calls ``settled`` with this id.
A_POLICY_IS_ASKED_FOR_BY_NAME = "evaluation-asks-for-a-policy-by-name"

#: The id of a change to the steps: waiting for a review is a step of
#: its own. Before, the workflow waited for a signal with a timer beside
#: it. A run that started before the change keeps the old way, so both
#: are still here and the use case calls ``changed`` with this id.
THE_PORT_WAITS = "the-port-holds-the-wait"


class EvaluatePullRequestUseCase:
    def __init__(
        self,
        execution: ExecutionService,
        observation: ObservationService,
        assessment: AssessmentService,
        reviews: AgentReviewService,
        publishing: PublishingService,
    ) -> None:
        self._execution = execution
        self._observation = observation
        self._assessment = assessment
        self._reviews = reviews
        self._publishing = publishing

    async def execute(
        self, request: EvaluatePullRequestRequest
    ) -> EvaluatePullRequestResponse:
        """Read the pull request, answer its policies and run its
        reviewers side by side, publish, and return what was found.
        """
        correlation = self._execution.correlation()
        observed = await self._observation.observe(
            request.ref, correlation, request.delivery_ids
        )
        corpus = observed.corpus

        self._execution.settled(A_POLICY_IS_ASKED_FOR_BY_NAME)
        assessed, reviewed = await asyncio.gather(
            self._assess(request, observed, correlation),
            self._review(observed, correlation),
        )

        findings = assessed.findings
        judge_status = assessed.status
        published = await self._publishing.publish(
            Publication(
                ref=observed.submission.ref,
                findings=findings,
                judge_status=judge_status,
                unavailable=assessed.unavailable,
                answered=assessed.answered,
                clauses=cited_clauses(corpus.doctrine, findings),
                corpus_version=corpus.version,
                correlation=correlation,
                head_sha=observed.head_sha,
                snapshot_id=observed.submission.snapshot_id,
                verdicts=tuple(r.verdict for r in reviewed if r.verdict),
                notes=tuple(r.note for r in reviewed if r.note),
                publish=request.publish,
            )
        )
        return EvaluatePullRequestResponse(
            ref=observed.submission.ref,
            title=observed.title,
            head_branch=observed.head_branch,
            base_branch=observed.base_branch,
            commit_count=observed.commit_count,
            file_count=observed.file_count,
            changed_lines=observed.changed_lines,
            corpus_version=corpus.version,
            findings=findings,
            judge_status=judge_status,
            publish_status=published.status,
            resolved=published.resolved,
            workflow_id=correlation.workflow_id,
            run_id=correlation.run_id,
        )

    async def _assess(
        self,
        request: EvaluatePullRequestRequest,
        observed: Observation,
        correlation: Correlation,
    ) -> Assessed:
        """Answer every policy the repository is reviewed for.

        Each policy is asked about in a step of its own, and the steps
        run side by side. So if one is rate limited, only that one is
        tried again.

        Nothing is asked in three cases:

        - This commit has already been judged under this corpus. The
          findings were recorded then. No policy answers now, so none of
          those findings is withdrawn.
        - The request asked for no judging.
        - No policy is declared for the repository.
        """
        if observed.judged_before:
            return Assessed(
                findings=(),
                status="already judged at this commit, against this corpus",
            )
        if not request.use_judge:
            return await self._assessment.unjudged(
                observed.submission,
                observed.corpus,
                correlation,
                observed.head_sha,
            )
        ref = observed.submission.ref
        policies = await self._assessment.policies(
            ref.forge, f"{ref.owner}/{ref.repo}"
        )
        if not policies:
            return Assessed(findings=(), status="reviewed for no policy")

        async def assess(policy: Answerable) -> Assessed:
            return await self._assessment.assess(
                policy,
                observed.submission,
                observed.corpus,
                correlation,
                observed.head_sha,
            )

        # The policies are asked in the order they were given. The
        # order steps start in is replayed, so it must not vary.
        answers = await asyncio.gather(*(assess(one) for one in policies))
        return Assessed(
            findings=tuple(f for one in answers for f in one.findings),
            status="; ".join(one.status for one in answers),
            unavailable=tuple(
                policy_id for one in answers for policy_id in one.unavailable
            ),
            answered=tuple(
                policy_id for one in answers for policy_id in one.answered
            ),
        )

    async def _review(
        self, observed: Observation, correlation: Correlation
    ) -> tuple[Reviewed, ...]:
        """Run every installed checkout agent on the last commit, side by
        side. Nothing is run if the pull request has no last commit.
        """
        if not observed.head_sha:
            return ()
        agents = await self._reviews.agents()
        if not agents:
            return ()
        reviewed = await asyncio.gather(
            *(
                self._review_one(observed, correlation, agent_id)
                for agent_id in agents
            )
        )
        return tuple(reviewed)

    async def _review_one(
        self, observed: Observation, correlation: Correlation, agent_id: str
    ) -> Reviewed:
        """One reviewer's review, or the reason there is none.

        A review that cannot be completed, because its runner failed or
        its grader would not answer, leaves that reviewer with no
        verdict. It does not fail the evaluation: the other reviewers'
        findings are still published.
        """
        try:
            return await self._review_run(observed, correlation, agent_id)
        except ReviewIncompleteError as exc:
            return Reviewed(reason=f"the review could not be completed: {exc}")

    async def _review_run(
        self, observed: Observation, correlation: Correlation, agent_id: str
    ) -> Reviewed:
        """Start one reviewer's run, wait for it and read it.

        If no run was started, the result is the verdict that was used
        again, or the reason.
        """
        asked = ReviewAsked(
            ref=observed.submission.ref,
            head_sha=observed.head_sha or "",
            base_sha=observed.base_sha,
            agent_id=agent_id,
            corpus_version=observed.corpus.version_for(agent_id),
            correlation=correlation,
        )
        dispatched = await self._reviews.dispatch(asked)
        handle = dispatched.handle
        if handle is None:
            return Reviewed(
                verdict=dispatched.reused, reason=dispatched.reason
            )
        waited = (
            await self._reviews.wait(asked, handle)
            if self._execution.changed(THE_PORT_WAITS)
            else await self._reviews.finished(agent_id, handle.remote_id)
        )
        # The time ran out. The run is ended before it is read, so that
        # it does not go on spending after the evaluation stopped
        # waiting.
        if not handle.is_finished and not waited:
            await self._reviews.stop(handle)
        return await self._reviews.collect(asked, handle)
