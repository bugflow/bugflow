"""Tests that the review activities are built over one judge and one
forge, and that judging stops at a run's ceiling.

Startup narrows the judge by dropping the policies no model answers
for, and the fan-out reads the narrowed set, so the two must be the
same object. One forge is given to observing, to publishing and to the
question of whether a pull request is open. Each test changes something
through one path and sees the effect through another.
"""

import tempfile
from pathlib import Path

import pytest
from temporalio.exceptions import ApplicationError

from bugflow.apps.worker.activities import ReviewActivities
from bugflow.apps.worker.tests.activities import (
    DOCTRINE,
    REF,
    REPO,
    RUN,
    SNAPSHOT,
    FailingForge,
    FakeDoctrine,
    FixedClock,
    NarrowingJudge,
    at_attempt,
    gating,
)
from bugflow.forge.domain.errors import ForgeRejectedError
from bugflow.forge.domain.models.pull_request import PullRequestSnapshot
from bugflow.forge.domain.services.forge import CommitState
from bugflow.forge.dtos.observe_pull_request import ObservePullRequestRequest
from bugflow.forge.infrastructure.in_memory_snapshots import (
    InMemorySnapshotStore,
)
from bugflow.review.domain.models.corpus import Corpus
from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.domain.models.submission import SubmissionRef
from bugflow.review.dtos.judge_pull_request import JudgePullRequestRequest
from bugflow.review.dtos.publish_findings import PublishFindingsRequest
from bugflow.review.infrastructure.in_memory_judge_archive import (
    InMemoryJudgeArchive,
)
from bugflow.review.infrastructure.in_memory_spend_bindings import (
    InMemorySpendBindings,
)
from bugflow.review.infrastructure.in_memory_spend_record import (
    InMemorySpendRecord,
)
from bugflow.review.tests.journal import QueryableJournal
from bugflow.shared.domain.values.budget import Budget
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


def built_with(
    judge: NarrowingJudge,
    snapshots: InMemorySnapshotStore,
    ceilings: InMemorySpendBindings | None = None,
    spend: InMemorySpendRecord | None = None,
) -> ReviewActivities:
    return ReviewActivities(
        forge=FailingForge(ForgeRejectedError("unused")),
        doctrine=FakeDoctrine(),
        judge=judge,
        journal=QueryableJournal(),
        snapshots=snapshots,
        archive=InMemoryJudgeArchive(),
        clock=FixedClock(),
        enforcement=gating(),
        ceilings=ceilings,
        spend=spend,
    )


def judging(
    snapshots: InMemorySnapshotStore, policy_id: str | None = "P-01"
) -> JudgePullRequestRequest:
    ref = snapshots.put(SNAPSHOT)
    return JudgePullRequestRequest(
        snapshot=SubmissionRef(snapshot_id=ref.snapshot_id, ref=ref.ref),
        corpus=Corpus(doctrine=DoctrineText(text=DOCTRINE.text), judge="j"),
        correlation=RUN,
        policy_id=policy_id,
    )


def test_a_policy_dropped_at_startup_is_not_offered_to_the_fan_out() -> None:
    judge = NarrowingJudge(("P-01", "P-02"))
    built = built_with(judge, InMemorySnapshotStore())
    judge.drop_unsupplied_policies()
    assert at_attempt(1).run(built.judge_policies, "github", REPO) == ["P-01"]


def test_the_fan_out_judges_only_what_startup_kept() -> None:
    """If the list of policies and the judging were given different
    judges, narrowing one would leave the other judging the dropped
    policy."""
    judge = NarrowingJudge(("P-01", "P-02"))
    snapshots = InMemorySnapshotStore()
    built = built_with(judge, snapshots)
    judge.drop_unsupplied_policies()

    response = at_attempt(1).run(built.judge, judging(snapshots, None))

    assert judge.assessed == ["P-01"]
    assert response.status == "judged by a-model"


class BudgetedForge:
    """A forge good for a fixed number of calls, whichever method they
    are made through."""

    def __init__(self, budget: int) -> None:
        self._budget = budget

    def _spend(self) -> None:
        if self._budget <= 0:
            raise ForgeRejectedError("budget exhausted")
        self._budget -= 1

    def fetch_snapshot(self, ref: PullRequestRef) -> PullRequestSnapshot:
        self._spend()
        return SNAPSHOT

    def is_open(self, ref: PullRequestRef) -> bool:
        self._spend()
        return True

    def add_comment(self, ref: PullRequestRef, marker: str, body: str) -> int:
        self._spend()
        return 1

    def set_labels(
        self,
        ref: PullRequestRef,
        add: frozenset[str],
        remove: frozenset[str],
    ) -> None:
        self._spend()

    def set_commit_status(
        self,
        ref: PullRequestRef,
        sha: str,
        context: str,
        state: CommitState,
        description: str,
    ) -> None:
        self._spend()


def publish_request() -> PublishFindingsRequest:
    return PublishFindingsRequest(
        ref=REF,
        findings=(),
        judge_status="skipped: no judge configured",
        corpus_version="v1",
        correlation=RUN,
    )


def test_is_open_observe_and_publish_share_one_forges_budget() -> None:
    built = ReviewActivities(
        forge=BudgetedForge(budget=2),
        doctrine=FakeDoctrine(),
        judge=None,
        journal=QueryableJournal(),
        snapshots=InMemorySnapshotStore(),
        archive=InMemoryJudgeArchive(),
        clock=FixedClock(),
        enforcement=gating(),
    )
    # The two calls the forge is good for: one asking whether the pull
    # request is open, one observing it.
    assert at_attempt(1).run(built.is_open, REF) is True
    at_attempt(1).run(
        built.observe, ObservePullRequestRequest(ref=REF, correlation=RUN)
    )
    # Publishing finds nothing left, which it could only do if it has
    # the forge the other two just used.
    with pytest.raises(ApplicationError) as raised:
        at_attempt(1).run(built.publish, publish_request())
    assert raised.value.non_retryable


def test_saying_where_a_review_would_run_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worktree service creates its own directory, and a runner that
    fetches the repository never reads one."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    built = built_with(NarrowingJudge(("P-01",)), InMemorySnapshotStore())
    first = built._worktree_for(None)  # type: ignore[arg-type]
    second = built._worktree_for(None)  # type: ignore[arg-type]
    assert first != second
    assert list(tmp_path.iterdir()) == []


def allowing(usd: float) -> InMemorySpendBindings:
    held = InMemorySpendBindings()
    held.declare(
        SpendBinding(
            scope=SpendScope(forge="github", repo=REPO),
            budget=Budget(usd=usd, turns=None),
            per="event",
        )
    )
    return held


def run_has_spent(usd: float) -> InMemorySpendRecord:
    held = InMemorySpendRecord()
    held.run_costs = [(RUN.run_id, usd)]
    return held


def test_a_run_that_has_spent_its_ceiling_judges_nothing_more() -> None:
    """Judging is spending and is capped like any other. The model is
    not called at all."""
    judge = NarrowingJudge(("P-01",))
    snapshots = InMemorySnapshotStore()
    built = built_with(judge, snapshots, allowing(2.50), run_has_spent(2.60))

    response = at_attempt(1).run(built.judge, judging(snapshots))

    assert judge.assessed == []
    assert response.findings == ()
    assert response.status == "this run is allowed $2.50 and has spent $2.60"


def test_a_policy_the_money_did_not_reach_is_unavailable() -> None:
    """Not answered and not clean: a policy that did not run withdraws
    nothing, so reading it as one that found nothing would retract what
    the last evaluation raised."""
    judge = NarrowingJudge(("P-01",))
    snapshots = InMemorySnapshotStore()
    built = built_with(judge, snapshots, allowing(2.50), run_has_spent(2.60))

    response = at_attempt(1).run(built.judge, judging(snapshots))

    assert response.unavailable == ("P-01",)
    assert response.answered == ()


def test_a_run_with_room_still_judges() -> None:
    judge = NarrowingJudge(("P-01",))
    snapshots = InMemorySnapshotStore()
    built = built_with(judge, snapshots, allowing(2.50), run_has_spent(0.40))

    response = at_attempt(1).run(built.judge, judging(snapshots))

    assert judge.assessed == ["P-01"]
    assert response.status == "judged by a-model"


def test_a_deployment_that_bound_nothing_judges_as_before() -> None:
    judge = NarrowingJudge(("P-01",))
    snapshots = InMemorySnapshotStore()
    built = built_with(judge, snapshots)

    at_attempt(1).run(built.judge, judging(snapshots))

    assert judge.assessed == ["P-01"]
