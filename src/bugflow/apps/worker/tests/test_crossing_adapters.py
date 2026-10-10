"""Tests of the adapters between contexts: each calls the other
context's interface and carries every field across.

One test for each adapter, against a stand-in written by hand for the
interface it wraps. A stand-in refuses a call the real interface does
not make, where a mock would answer it.
"""

import dataclasses
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from bugflow.apps.worker.conversation import ForgeConversation
from bugflow.apps.worker.delegated_work import (
    WorkDelegation,
    _handle,
    _run,
    _task,
    _work_handle,
    _work_run,
)
from bugflow.apps.worker.publication import ForgePublication
from bugflow.apps.worker.review_scope import DeclaredReviewScope
from bugflow.apps.worker.submission_source import ForgeSubmissionSource
from bugflow.apps.worker.worktree import WorkWorktrees
from bugflow.forge.domain.errors import ForgeRejectedError
from bugflow.forge.domain.models.pull_request import (
    Authorship,
    ChangedFile,
    CommitSnapshot,
    PullRequestSnapshot,
    SnapshotRef,
)
from bugflow.forge.domain.values.conversation import (
    PullRequestState,
)
from bugflow.forge.domain.values.conversation import (
    Reaction as ForgeReaction,
)
from bugflow.forge.domain.values.review_scope import ReviewScope
from bugflow.review.domain.errors import (
    AgentTemporarilyUnavailableError,
    AgentUnavailableError,
    PublicationRejectedError,
    WorktreeUnavailableError,
)
from bugflow.review.domain.models.conversation import Closing, Reaction
from bugflow.review.domain.models.delegation import Handle, Run, RunParty, Task
from bugflow.review.domain.models.review_declaration import JudgedPolicies
from bugflow.review.domain.models.submission import SubmissionRef
from bugflow.review.infrastructure.in_memory_review_declaration import (
    InMemoryJudgedPolicies,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.work.domain.errors import (
    AgentTemporarilyUnavailableError as WorkAgentTemporarilyUnavailableError,
)
from bugflow.work.domain.errors import (
    AgentUnavailableError as WorkAgentUnavailableError,
)
from bugflow.work.domain.errors import (
    WorktreeUnavailableError as WorkWorktreeUnavailableError,
)
from bugflow.work.domain.models.agent import (
    AgentHandle,
    AgentRun,
    AgentTask,
    Party,
)

REF = PullRequestRef(owner="o", repo="r", number=1)


class FakeSnapshots:
    """Refuses any reference it was not given a snapshot for."""

    def __init__(
        self, ref: SnapshotRef, snapshot: PullRequestSnapshot
    ) -> None:
        self._by_ref = {ref: snapshot}

    def get(self, reference: SnapshotRef) -> PullRequestSnapshot:
        return self._by_ref[reference]

    def put(self, snapshot: PullRequestSnapshot) -> SnapshotRef:
        raise NotImplementedError


def test_forge_submission_source_translates_a_snapshot_into_a_submission() -> (
    None
):
    snapshot = PullRequestSnapshot(
        ref=REF,
        title="Add a thing",
        body="Does the thing.",
        head_branch="a-thing",
        base_branch="master",
        commits=(
            CommitSnapshot(
                sha="deadbeef",
                message="Add the thing",
                author=Authorship(name="a", email="a@example.com"),
            ),
        ),
        files=(
            ChangedFile(
                path="thing.py", additions=2, deletions=0, patch="+x\n+y"
            ),
        ),
    )
    ref = SnapshotRef(snapshot_id="abc", ref=REF)
    source = ForgeSubmissionSource(FakeSnapshots(ref, snapshot))

    submission = source.get(SubmissionRef(snapshot_id="abc", ref=REF))

    assert submission.title == "Add a thing"
    assert submission.body == "Does the thing."
    assert [c.sha for c in submission.commits] == ["deadbeef"]
    assert [c.message for c in submission.commits] == ["Add the thing"]
    assert submission.files[0].path == "thing.py"
    assert submission.files[0].additions == 2
    assert submission.files[0].patch == "+x\n+y"


class FakeForge:
    """Refuses a write about a pull request it was not asked about."""

    def __init__(self, ref: PullRequestRef) -> None:
        self._ref = ref
        self.comments: list[str] = []
        self.labelled: tuple[frozenset[str], frozenset[str]] | None = None
        self.rejects_status = False

    def fetch_snapshot(self, ref: PullRequestRef) -> PullRequestSnapshot:
        raise NotImplementedError

    def is_open(self, ref: PullRequestRef) -> bool:
        raise NotImplementedError

    def add_comment(self, ref: PullRequestRef, marker: str, body: str) -> int:
        assert ref == self._ref
        self.comments.append(body)
        return 42

    def set_labels(
        self,
        ref: PullRequestRef,
        add: frozenset[str],
        remove: frozenset[str],
    ) -> None:
        assert ref == self._ref
        self.labelled = (add, remove)

    def set_commit_status(
        self,
        ref: PullRequestRef,
        sha: str,
        context: str,
        state: str,
        description: str,
    ) -> None:
        assert ref == self._ref
        if self.rejects_status:
            raise ForgeRejectedError("the token may not set statuses")


def test_forge_publication_calls_forge_and_returns_the_comment_id() -> None:
    forge = FakeForge(REF)
    publication = ForgePublication(forge)
    assert publication.add_comment(REF, "<!-- m -->", "hello") == 42
    assert forge.comments == ["hello"]
    publication.set_labels(REF, frozenset({"review:pass"}), frozenset())
    assert forge.labelled == (frozenset({"review:pass"}), frozenset())


def test_forge_publication_translates_a_rejected_status() -> None:
    forge = FakeForge(REF)
    forge.rejects_status = True
    publication = ForgePublication(forge)
    with pytest.raises(PublicationRejectedError):
        publication.set_commit_status(REF, "sha", "ctx", "success", "ok")


class FakeWorktrees:
    def __init__(self, unavailable: bool = False) -> None:
        self.unavailable = unavailable
        self.prepared: tuple[PullRequestRef, str, Path, str] | None = None

    def prepare(
        self,
        ref: PullRequestRef,
        head_sha: str,
        into: Path,
        base_sha: str = "",
    ) -> tuple[str, ...]:
        if self.unavailable:
            raise WorkWorktreeUnavailableError("no git here")
        self.prepared = (ref, head_sha, into, base_sha)
        return (".env",)


def test_work_worktrees_calls_the_real_adapter_and_returns_removed() -> None:
    worktrees = FakeWorktrees()
    crossing = WorkWorktrees(worktrees)
    removed = crossing.prepare(REF, "sha1", Path("/tmp/w"), "sha0")
    assert removed == (".env",)
    assert worktrees.prepared == (REF, "sha1", Path("/tmp/w"), "sha0")


def test_work_worktrees_translates_its_own_unavailable_error() -> None:
    crossing = WorkWorktrees(FakeWorktrees(unavailable=True))
    with pytest.raises(WorktreeUnavailableError):
        crossing.prepare(REF, "sha1", Path("/tmp/w"))


class FakeDelegatedWork:
    """Refuses a handle it did not hand out itself."""

    def __init__(self) -> None:
        self.waited: list[float] = []
        self.dispatched: AgentTask | None = None
        self.collected: AgentHandle | None = None
        self.stopped: AgentHandle | None = None
        self.unavailable = False
        self.retry_after: float | None = None

    @property
    def runner(self) -> str:
        return "stub"

    @property
    def fingerprint(self) -> str:
        return "fp"

    def dispatch(self, task: AgentTask) -> AgentHandle:
        if self.retry_after is not None:
            raise WorkAgentTemporarilyUnavailableError(
                "quota exhausted", retry_after=self.retry_after
            )
        if self.unavailable:
            raise WorkAgentUnavailableError("no runner")
        self.dispatched = task
        return AgentHandle(runner="stub", fingerprint="fp", remote_id="r1")

    @property
    def notifies(self) -> bool:
        return False

    def wait(self, handle: AgentHandle, patience: float) -> bool:
        self.waited.append(patience)
        return True

    def collect(self, handle: AgentHandle) -> AgentRun:
        if self.retry_after is not None:
            raise WorkAgentTemporarilyUnavailableError(
                "quota exhausted", retry_after=self.retry_after
            )
        self.collected = handle
        if handle.run is not None:
            return handle.run
        return AgentRun(outcome="completed", artifact={"write_up": "done"})

    def stop(self, handle: AgentHandle) -> None:
        self.stopped = handle


def test_work_delegation_translates_a_task_and_handle_faithfully() -> None:
    agent = FakeDelegatedWork()
    delegation = WorkDelegation(agent)
    handle = delegation.dispatch(
        Task(instructions="review this", inputs="/tmp/w")
    )
    assert agent.dispatched is not None
    assert agent.dispatched.instructions == "review this"
    assert handle.runner == "stub"
    assert handle.remote_id == "r1"

    run = delegation.collect(handle)
    assert run.outcome == "completed"
    assert run.artifact == {"write_up": "done"}


def test_work_delegation_preserves_a_run_already_on_the_handle() -> None:
    """A runner that finishes inside dispatch carries its run in the
    handle; collecting it must not discard that and ask the real adapter
    to fetch a run that was never dispatched remotely."""
    agent = FakeDelegatedWork()
    delegation = WorkDelegation(agent)
    finished = Handle(
        runner="stub",
        fingerprint="fp",
        run=Run(outcome="completed", artifact={"write_up": "inline"}),
    )
    run = delegation.collect(finished)
    assert run.artifact == {"write_up": "inline"}
    # The real adapter saw the run already on the handle, not an empty one.
    assert agent.collected is not None
    assert agent.collected.run is not None
    assert agent.collected.run.artifact == {"write_up": "inline"}


def test_work_delegation_translates_its_own_unavailable_error() -> None:
    agent = FakeDelegatedWork()
    agent.unavailable = True
    delegation = WorkDelegation(agent)
    with pytest.raises(AgentUnavailableError):
        delegation.dispatch(Task(instructions="review this"))


def test_work_delegation_preserves_retry_after_on_dispatch() -> None:
    """A quota or a busy host is worth trying again, and when: dropping
    retry_after here loses that to a plain AgentUnavailableError, the
    same failure a runner that will never come back would raise."""
    agent = FakeDelegatedWork()
    agent.retry_after = 30.0
    delegation = WorkDelegation(agent)
    with pytest.raises(AgentTemporarilyUnavailableError) as excinfo:
        delegation.dispatch(Task(instructions="review this"))
    assert excinfo.value.retry_after == 30.0


def test_work_delegation_preserves_retry_after_on_collect() -> None:
    agent = FakeDelegatedWork()
    agent.retry_after = 12.0
    delegation = WorkDelegation(agent)
    handle = Handle(runner="stub", fingerprint="fp", remote_id="r1")
    with pytest.raises(AgentTemporarilyUnavailableError) as excinfo:
        delegation.collect(handle)
    assert excinfo.value.retry_after == 12.0


def filled(cls: Any) -> Any:
    """An instance with a distinct value, never a default, in every field.

    Generic over the fields on purpose: a field added to either side and
    forgotten in the translation fails here without this test being edited.
    """
    values: dict[str, Any] = {}
    for n, f in enumerate(dataclasses.fields(cls), start=1):
        kind = str(f.type)
        if "Run" in kind and cls in (AgentHandle, Handle):
            values[f.name] = filled(AgentRun if cls is AgentHandle else Run)
        elif "Party" in kind:
            # A tuple of records rather than of strings, so each party
            # crosses field for field as the run around it does.
            values[f.name] = (
                filled(Party if "RunParty" not in kind else RunParty),
            )
        elif "dict" in kind or "Mapping" in kind:
            values[f.name] = {f.name: float(n)}
        elif "tuple" in kind:
            values[f.name] = (f.name,)
        elif "float" in kind:
            values[f.name] = float(n)
        elif "int" in kind:
            values[f.name] = n
        else:
            values[f.name] = f"{f.name}-value"
    return cls(**values)


def test_nothing_is_lost_crossing_to_work_and_back() -> None:
    """The review context's task, handle and run mirror the work
    context's field for field, so what a workflow recorded with one
    still reads with the other. A translation that drops a field would
    break that silently."""
    run, handle = filled(AgentRun), filled(AgentHandle)
    assert asdict(_work_run(_run(run))) == asdict(run)
    assert asdict(_work_handle(_handle(handle))) == asdict(handle)
    assert asdict(_task(filled(Task))) == asdict(filled(Task))


class FakeConversations:
    """Refuses a question about a pull request it was not asked about."""

    def __init__(self, ref: PullRequestRef) -> None:
        self._ref = ref

    def reactions(
        self, ref: PullRequestRef, comment_id: int
    ) -> tuple[ForgeReaction, ...]:
        assert (ref, comment_id) == (self._ref, 7)
        return (
            ForgeReaction(content="+1", login="a", reacted_at=AT),
            ForgeReaction(content="confused", login="b"),
        )

    def state(self, ref: PullRequestRef) -> PullRequestState:
        assert ref == self._ref
        return PullRequestState(merged=True, head_sha="deadbeef")


AT = datetime(2030, 3, 12, tzinfo=UTC)


def test_forge_conversation_carries_reactions_and_the_closing_across() -> None:
    conversation = ForgeConversation(FakeConversations(REF))
    assert conversation.reactions(REF, 7) == (
        Reaction(content="+1", login="a", reacted_at=AT),
        Reaction(content="confused", login="b"),
    )
    assert conversation.state(REF) == Closing(merged=True, head_sha="deadbeef")


def test_a_review_scope_says_what_is_held_and_what_a_repository_asked() -> (
    None
):
    """A policy switched off for a repository is told from one that ran
    and found nothing."""
    declared = InMemoryJudgedPolicies()
    declared.declare(
        JudgedPolicies(forge="github", repo="o/r", policies=("P-02", "P-07"))
    )
    scope = DeclaredReviewScope(("P-01", "P-02"), declared)
    assert scope.scope_for("github", "o/r") == ReviewScope(
        held=("P-01", "P-02"), reviewed_for=("P-02",)
    )
    assert scope.scope_for("github", "o/other").reviewed_for == ()


def test_a_server_with_no_declarations_reviews_for_all_it_holds() -> None:
    scope = DeclaredReviewScope(("P-01", "P-02"), None)
    assert scope.scope_for("github", "o/r").reviewed_for == ("P-01", "P-02")
