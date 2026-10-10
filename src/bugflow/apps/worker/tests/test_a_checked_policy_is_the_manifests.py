"""Tests that a policy a check answers is the one a reviewer's manifest
names: its id, the clause its findings cite, and the reviewer it
belongs to. The worker's code names no policy."""

import ast
import re
from pathlib import Path

from bugflow.apps.worker import activities as module
from bugflow.apps.worker.activities import Checked, ReviewActivities
from bugflow.apps.worker.tests.activities import (
    DOCTRINE,
    REF,
    REPO,
    RUN,
    FailingForge,
    FakeDoctrine,
    FixedClock,
    NarrowingJudge,
    at_attempt,
)
from bugflow.forge.domain.errors import ForgeRejectedError
from bugflow.forge.domain.models.pull_request import PullRequestSnapshot
from bugflow.forge.infrastructure.in_memory_snapshots import (
    InMemorySnapshotStore,
)
from bugflow.review.domain.facts import POLICY_CHECKED
from bugflow.review.domain.models.corpus import Corpus
from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.submission import SubmissionRef
from bugflow.review.dtos.assess_policy import AssessPolicyRequest
from bugflow.review.infrastructure.in_memory_judge_archive import (
    InMemoryJudgeArchive,
)
from bugflow.review.tests.journal import QueryableJournal

DASH = "\u2014"
DASHED = PullRequestSnapshot(
    ref=REF,
    title="Add a poller",
    body=f"It polls {DASH} every minute.",
    head_branch="a-poller",
    base_branch="master",
    commits=(),
    files=(),
)


class Built:
    """The activities over a judge of one policy, with one more policy
    given to a check."""

    def __init__(self) -> None:
        self.judge = NarrowingJudge(("P-01",))
        self.journal = QueryableJournal()
        self.snapshots = InMemorySnapshotStore()
        self.activities = ReviewActivities(
            forge=FailingForge(ForgeRejectedError("unused")),
            doctrine=FakeDoctrine(),
            judge=self.judge,
            journal=self.journal,
            snapshots=self.snapshots,
            archive=InMemoryJudgeArchive(),
            clock=FixedClock(),
            checked={"P-09": Checked(agent_id="prose", clause="EX-21")},
        )

    def asking(self, policy_id: str) -> AssessPolicyRequest:
        ref = self.snapshots.put(DASHED)
        return AssessPolicyRequest(
            policy_id=policy_id,
            snapshot=SubmissionRef(snapshot_id=ref.snapshot_id, ref=ref.ref),
            corpus=Corpus(
                doctrine=DoctrineText(text=DOCTRINE.text),
                judge="j",
                installed={"prose": "prose-3"},
            ),
            correlation=RUN,
        )


def test_a_checked_policy_is_answered_under_the_manifests_ids() -> None:
    built = Built()

    response = at_attempt(1).run(
        built.activities.assess_policy, built.asking("P-09")
    )

    (finding,) = response.findings
    assert (finding.policy_id, finding.clause) == ("P-09", "EX-21")
    assert (finding.agent_id, finding.corpus_version) == ("prose", "prose-3")
    assert response.answered == ("P-09",)
    assert built.judge.assessed == []
    assert [e.event_type for e in built.journal.entries].count(
        POLICY_CHECKED
    ) == 1


def test_any_other_policy_goes_to_the_judge() -> None:
    built = Built()

    response = at_attempt(1).run(
        built.activities.assess_policy, built.asking("P-01")
    )

    assert built.judge.assessed == ["P-01"]
    assert response.findings == ()


def test_a_repository_is_reviewed_for_the_checked_policy_too() -> None:
    built = Built()
    offered = at_attempt(1).run(
        built.activities.review_policies, "github", REPO
    )
    assert [(one.policy_id, one.model_class) for one in offered] == [
        ("P-01", ""),
        ("P-09", ""),
    ]


def test_the_activities_name_no_policy() -> None:
    """Statically: no string in the module looks like a policy's id or
    a clause's."""
    source = Path(module.__file__).read_text()
    named = [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and re.fullmatch(r"[A-Z]{1,6}-\d+", node.value)
    ]
    assert named == []
