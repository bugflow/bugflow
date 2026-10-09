"""Tests of the parts of the work domain that compute something: which
paths count as instructions, how a repository's name is read, and how a
dispatch is read back from its journal entry."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.budget import Budget
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.work.domain.facts import AGENT_DISPATCHED
from bugflow.work.domain.models.agent import AgentHandle, AgentRun
from bugflow.work.domain.models.backfill import WatchedRepository
from bugflow.work.domain.models.journal import dispatched_from_entry
from bugflow.work.domain.values.sandbox import instruction_sources, instructs


@pytest.mark.parametrize(
    "path",
    [
        "CLAUDE.md",
        "AGENTS.md",
        "docs/guide/AGENTS.md",
        ".cursorrules",
        ".claude/settings.json",
        "services/api/.claude/hooks/start.sh",
        ".github/copilot-instructions.md",
        "packages/web/.github/copilot-instructions.md",
        ".claude",
        "tools\\.codex\\config.toml",
    ],
)
def test_a_path_a_runner_might_read_as_instructions(path: str) -> None:
    assert instructs(path)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "README.md",
        "src/claude.py",
        "docs/AGENTS.md.txt",
        ".github/workflows/ci.yml",
        "notes/copilot-instructions.md",
        "claude/settings.json",
    ],
)
def test_a_path_that_is_not_an_instruction(path: str) -> None:
    assert not instructs(path)


def test_instruction_sources_are_picked_out_and_sorted() -> None:
    paths = ["src/app.py", "docs/CLAUDE.md", ".agents/skills/x.md", "a.txt"]
    assert instruction_sources(paths) == (
        ".agents/skills/x.md",
        "docs/CLAUDE.md",
    )


def test_a_repository_is_on_github_unless_it_says_otherwise() -> None:
    assert WatchedRepository.parse(" orchard/pear-tree ") == WatchedRepository(
        forge="github", owner="orchard", repo="pear-tree"
    )
    assert WatchedRepository.parse(
        "github:orchard/pear-tree"
    ) == WatchedRepository(forge="github", owner="orchard", repo="pear-tree")
    assert WatchedRepository.parse(
        "forgejo:orchard/pear.tree"
    ) == WatchedRepository(forge="forgejo", owner="orchard", repo="pear.tree")


@pytest.mark.parametrize(
    "text", ["", "pear-tree", "gitlab:orchard/pear-tree", "a/b/c", "a b/c"]
)
def test_anything_else_is_not_a_repository(text: str) -> None:
    with pytest.raises(ValueError):
        WatchedRepository.parse(text)


def test_a_handle_is_finished_only_if_it_carries_its_run() -> None:
    working = AgentHandle(runner="hosted", fingerprint="f", remote_id="s-1")
    done = AgentHandle(
        runner="stub", fingerprint="f", run=AgentRun(outcome="completed")
    )
    assert not working.is_finished
    assert done.is_finished


def _dispatch(payload: dict[str, Any]) -> JournalEntry:
    return JournalEntry(
        event_id=uuid4(),
        occurred_at=datetime(2030, 1, 2, 3, 4, tzinfo=UTC),
        event_type=AGENT_DISPATCHED,
        forge="github",
        repo="orchard/pear-tree",
        pr_number=7,
        commit_sha="c0ffee",
        corpus_version="v1",
        workflow_id="wf-1",
        run_id="run-1",
        payload=payload,
    )


def test_a_dispatch_is_read_back_from_its_journal_entry() -> None:
    work = dispatched_from_entry(
        _dispatch(
            {
                "agent_id": "reviewer",
                "step": "dispatched",
                "runner": "hosted",
                "fingerprint": "abc",
                "remote_id": "s-1",
                "budget": {"usd": 2, "turns": 30, "minutes": 9},
            }
        )
    )
    assert work.correlation == Correlation(workflow_id="wf-1", run_id="run-1")
    assert (work.forge, work.repo, work.pr_number) == (
        "github",
        "orchard/pear-tree",
        7,
    )
    assert work.agent_id == "reviewer"
    assert work.handle == AgentHandle(
        runner="hosted",
        fingerprint="abc",
        remote_id="s-1",
        budget=Budget(usd=2.0, turns=30.0),
    )


def test_a_limit_the_entry_does_not_name_takes_the_default() -> None:
    work = dispatched_from_entry(_dispatch({"budget": {"usd": 2}}))
    assert work.handle.budget is not None
    assert work.handle.budget.usd == 2.0
    assert work.handle.budget.turns == Budget().turns


def test_an_entry_with_nothing_recorded_gives_an_empty_handle() -> None:
    work = dispatched_from_entry(_dispatch({}))
    assert work.agent_id == ""
    assert work.handle == AgentHandle(runner="", fingerprint="")
