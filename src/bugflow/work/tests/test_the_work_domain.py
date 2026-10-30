"""Tests of the parts of the work domain that compute something: which
paths count as instructions, how a repository's name is read, and how a
dispatch is read back from its journal entry."""

import pytest

from bugflow.work.domain.models.agent import AgentHandle, AgentRun
from bugflow.work.domain.models.backfill import WatchedRepository
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
