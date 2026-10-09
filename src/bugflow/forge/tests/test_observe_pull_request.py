"""Tests of observing a pull request: the snapshot is stored, the
observation is recorded, and content that was already reviewed is
recognised."""

from datetime import UTC, datetime

from bugflow.forge.domain import facts
from bugflow.forge.domain.models.pull_request import (
    ChangedFile,
    CommitSnapshot,
    PullRequestSnapshot,
)
from bugflow.forge.domain.values.evaluation_regime import EvaluationRegime
from bugflow.forge.domain.values.review_scope import ReviewScope
from bugflow.forge.dtos.observe_pull_request import (
    ObservePullRequestRequest,
    ObservePullRequestResponse,
)
from bugflow.forge.infrastructure.in_memory_snapshots import (
    InMemorySnapshotStore,
)
from bugflow.forge.tests.journal import QueryableJournal
from bugflow.forge.usecases.observe_pull_request import (
    ObservePullRequestUseCase,
)
from bugflow.shared.domain.models.recorder import Recorder
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="o", repo="r", number=6)
RUN = Correlation(workflow_id="a-workflow", run_id="a-run")
NOW = datetime(2026, 9, 21, tzinfo=UTC)
SNAPSHOT = PullRequestSnapshot(
    ref=REF,
    title="A title",
    body="A description",
    head_branch="a-branch",
    base_branch="master",
    commits=(CommitSnapshot(sha="c" * 40, message="A change"),),
    files=(ChangedFile(path="a.py", additions=2, deletions=1, patch="@@"),),
)
REGIME = EvaluationRegime(
    doctrine_text="The rules.",
    judge_fingerprint="a-judge",
    version="v1",
    components={"doctrine": "d1"},
    installed={"an-agent": "a1"},
)


class Forge:
    def fetch_snapshot(self, ref: PullRequestRef) -> PullRequestSnapshot:
        return SNAPSHOT


class Regime:
    def current(self) -> EvaluationRegime:
        return REGIME


class Clock:
    def now(self) -> datetime:
        return NOW


class Scope:
    def scope_for(self, forge: str, repo: str) -> ReviewScope:
        return ReviewScope(held=("ED-01", "SC-01"), reviewed_for=("ED-01",))


def observe(
    journal: QueryableJournal,
    declared: tuple[str, ...] = (),
    scope: Scope | None = None,
) -> ObservePullRequestResponse:
    return ObservePullRequestUseCase(
        Forge(),  # type: ignore[arg-type]
        Regime(),
        InMemorySnapshotStore(),
        journal,
        journal,
        Clock(),
        scope,
    ).execute(
        ObservePullRequestRequest(
            ref=REF,
            correlation=RUN,
            delivery_ids=("first", "second"),
            declared=declared,
        )
    )


def reviewed(
    journal: QueryableJournal,
    policy: str,
    status: str = "judged by a-model",
    version: str = "v1",
    content: str = SNAPSHOT.content_id,
) -> None:
    """Record that a judge was asked about ``content`` for ``policy``."""
    journal.append(
        [
            Recorder(REF, RUN, version, NOW).entry(
                facts.JUDGE_INVOKED,
                f"{policy}/{status}/{version}/{content}",
                {
                    "policy_id": policy,
                    "status": status,
                    "identity": {"input_hash": content},
                },
            )
        ]
    )


def test_the_snapshot_is_stored_and_the_observation_recorded() -> None:
    journal = QueryableJournal()

    answer = observe(journal, scope=Scope())

    assert answer.snapshot.snapshot_id == SNAPSHOT.content_id
    assert answer.summary == SNAPSHOT.summary()
    assert answer.corpus == REGIME
    (entry,) = journal.entries
    assert entry.event_type == "pr.observed"
    assert entry.commit_sha == "c" * 40
    assert entry.corpus_version == "v1"
    assert entry.payload["delivery_id"] == "second"
    assert entry.payload["delivery_ids"] == ["first", "second"]
    assert entry.payload["snapshot_id"] == SNAPSHOT.content_id
    assert entry.payload["reviewed_for"] == ["ED-01"]
    assert entry.payload["held"] == ["ED-01", "SC-01"]
    assert entry.payload["changed_lines"] == 3


def test_with_no_scope_service_nothing_is_said_about_scope() -> None:
    journal = QueryableJournal()

    observe(journal)

    assert "reviewed_for" not in journal.entries[0].payload
    assert "held" not in journal.entries[0].payload


def test_content_never_reviewed_has_not_been_reviewed_before() -> None:
    assert observe(QueryableJournal()).judged_before is False


def test_content_is_reviewed_before_when_every_policy_has_an_answer() -> None:
    journal = QueryableJournal()
    reviewed(journal, "ED-01")

    assert observe(journal, declared=("ED-01",)).judged_before is True
    # A policy added since has no answer yet, so the content is reviewed
    # again.
    assert observe(journal, declared=("ED-01", "SC-01")).judged_before is (
        False
    )
    reviewed(journal, "SC-01")
    assert observe(journal, declared=("ED-01", "SC-01")).judged_before is (
        True
    )


def test_with_no_policies_named_any_answer_counts() -> None:
    journal = QueryableJournal()
    reviewed(journal, "ED-01")

    assert observe(journal).judged_before is True


def test_a_review_that_failed_does_not_count() -> None:
    journal = QueryableJournal()
    reviewed(journal, "ED-01", status="refused: rate limited")

    assert observe(journal, declared=("ED-01",)).judged_before is False


def test_a_review_under_other_rules_or_of_other_content_does_not_count() -> (
    None
):
    journal = QueryableJournal()
    reviewed(journal, "ED-01", version="v0")
    reviewed(journal, "ED-01", content="another-snapshot")

    assert observe(journal, declared=("ED-01",)).judged_before is False
