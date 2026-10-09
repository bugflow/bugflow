"""The interfaces to the steps of an evaluation.

The use case that runs an evaluation calls each step through one of
these. Every method that does work is ``async``, so that a workflow can
schedule the step and wait for it. In a worker each step runs another
use case. In a test each is a stand-in.
"""

from typing import Protocol

from bugflow.review.domain.models.corpus import Corpus
from bugflow.review.domain.models.delegation import Handle
from bugflow.review.domain.models.evaluation import (
    Answerable,
    Assessed,
    Dispatched,
    Observation,
    Publication,
    Published,
    ReviewAsked,
    Reviewed,
)
from bugflow.review.domain.models.submission import SubmissionRef
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class ExecutionService(Protocol):
    """What the evaluation asks about the workflow run it is in.

    The second and third methods are for changing the steps of an
    evaluation while some evaluations are still running. A run that
    started before a change must keep taking the old steps, or the
    workflow engine cannot replay what it recorded. Each change has an
    id.
    """

    def correlation(self) -> Correlation:
        """The workflow run the evaluation is in."""
        ...

    def changed(self, change_id: str) -> bool:
        """Whether this run takes the new steps of the change.

        True for a run that started after the change was deployed, and
        for one replaying a history that took it. False for a run that
        was already going when the change was deployed.
        """
        ...

    def settled(self, change_id: str) -> None:
        """Say that no run is left that takes the old steps of the
        change.

        Once the old steps are deleted from the code, the call to
        ``changed`` is replaced by this call, in the same place. Runs
        whose history took the change still replay.
        """
        ...


class ObservationService(Protocol):
    async def observe(
        self,
        ref: PullRequestRef,
        correlation: Correlation,
        delivery_ids: tuple[str, ...],
    ) -> Observation:
        """Read the pull request and store its submission.
        ``delivery_ids`` are the forge deliveries that started the
        evaluation."""
        ...


class AssessmentService(Protocol):
    """Answers policies. The caller asks about a policy and does not
    know whether a judge or a check answers it."""

    async def policies(self, forge: str, repo: str) -> list[Answerable]:
        """Return the policies the repository is reviewed for, in
        order. A repository for which none are declared is reviewed for
        none."""
        ...

    async def assess(
        self,
        policy: Answerable,
        submission: SubmissionRef,
        corpus: Corpus,
        correlation: Correlation,
        head_sha: str | None = None,
    ) -> Assessed:
        """Answer one policy.

        ``head_sha`` is the commit, so that what is recorded can give
        it. A submission is identified by its content and does not say
        which commit it was read at.
        """
        ...

    async def unjudged(
        self,
        submission: SubmissionRef,
        corpus: Corpus,
        correlation: Correlation,
        head_sha: str | None = None,
    ) -> Assessed:
        """Return what an evaluation answers when it was asked to judge
        nothing. An evaluation can be asked that, to read a pull request
        without spending anything."""
        ...


class AgentReviewService(Protocol):
    """Runs the reviews of checkout agents. Every method except
    ``agents`` raises ``ReviewIncompleteError`` if it fails and trying
    again will not help."""

    async def agents(self) -> list[str]:
        """Return the agent ids of the installed checkout agents."""
        ...

    async def dispatch(self, asked: ReviewAsked) -> Dispatched:
        """Start one reviewer's review of one commit."""
        ...

    async def finished(self, agent_id: str, remote_id: str) -> bool:
        """Wait for the run's deadline or its end, and return whether it
        finished before the deadline. This is the older way to wait,
        kept for evaluations that started before ``wait`` existed."""
        ...

    async def wait(self, asked: ReviewAsked, handle: Handle) -> bool:
        """Wait for the run to have something to read, and return
        whether it has. False means the time ran out, not that the run
        failed. The caller collects the run either way."""
        ...

    async def stop(self, handle: Handle) -> None:
        """End the run."""
        ...

    async def collect(self, asked: ReviewAsked, handle: Handle) -> Reviewed:
        """Read the run, have its write-up graded, and return the
        review."""
        ...


class PublishingService(Protocol):
    async def publish(self, publication: Publication) -> Published:
        """Write what the evaluation found to the pull request."""
        ...
