"""Stand-ins the tests of the review activities share: one pull request,
a clock, a doctrine, two forges and a judge."""

import dataclasses
from datetime import UTC, datetime

from temporalio.testing import ActivityEnvironment

from bugflow.forge.domain.models.pull_request import PullRequestSnapshot
from bugflow.forge.domain.services.forge import CommitState
from bugflow.method.domain.models.doctrine import Doctrine
from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.enforcement import GATE
from bugflow.review.domain.models.judge_assessment import JudgeAssessment
from bugflow.review.domain.models.submission import Submission
from bugflow.review.infrastructure.in_memory_enforcement import (
    InMemoryEnforcement,
)
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="example-org", repo="widgets", number=1)
REPO = f"{REF.owner}/{REF.repo}"
RUN = Correlation(workflow_id="pr/github/example-org/widgets/1", run_id="r-1")
DOCTRINE = Doctrine(text="EX-1. A description says what changed.")
SNAPSHOT = PullRequestSnapshot(
    ref=REF,
    title="Add a thing",
    body="Adds a thing.",
    head_branch="a-thing",
    base_branch="master",
    commits=(),
    files=(),
)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2030, 3, 12, tzinfo=UTC)


class FakeDoctrine:
    def load(self) -> Doctrine:
        return DOCTRINE


def gating() -> InMemoryEnforcement:
    """The repository of ``REF``, bound to the profile that publishes
    and fails a status."""
    enforcement = InMemoryEnforcement()
    enforcement.bind(REF.forge, REPO, GATE)
    return enforcement


def at_attempt(attempt: int) -> ActivityEnvironment:
    """Temporal's activity test environment, saying which attempt this
    is."""
    environment = ActivityEnvironment()
    environment.info = dataclasses.replace(environment.info, attempt=attempt)
    return environment


class FailingForge:
    """A forge every call to which raises the error it was given."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def fetch_snapshot(self, ref: PullRequestRef) -> PullRequestSnapshot:
        raise self._error

    def is_open(self, ref: PullRequestRef) -> bool:
        raise self._error

    def add_comment(self, ref: PullRequestRef, marker: str, body: str) -> int:
        raise self._error

    def set_labels(
        self,
        ref: PullRequestRef,
        add: frozenset[str],
        remove: frozenset[str],
    ) -> None:
        raise self._error

    def set_commit_status(
        self,
        ref: PullRequestRef,
        sha: str,
        context: str,
        state: CommitState,
        description: str,
    ) -> None:
        raise self._error


class NarrowingJudge:
    """A judge that finds nothing, and whose policies can be narrowed
    after it is built, as the real judge's are at startup."""

    model_id = "a-model"
    fingerprint = "a-fingerprint"

    def __init__(self, policies: tuple[str, ...]) -> None:
        self._policies = list(policies)
        self.assessed: list[str] = []

    @property
    def policies(self) -> tuple[str, ...]:
        return tuple(self._policies)

    def drop_unsupplied_policies(self) -> tuple[str, ...]:
        """Drop the last policy, and return it."""
        dropped, self._policies = (
            tuple(self._policies[-1:]),
            self._policies[:-1],
        )
        return dropped

    def assess(
        self,
        submission: Submission,
        doctrine: DoctrineText,
        policy_id: str,
    ) -> JudgeAssessment:
        self.assessed.append(policy_id)
        return JudgeAssessment(findings=(), model="a-model")
