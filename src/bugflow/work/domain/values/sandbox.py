"""The rule for which files are removed from a worktree before a runner
reads it.

Many coding agents read instruction files from the directory they work
in: ``CLAUDE.md``, ``AGENTS.md`` and others. Some also load settings,
plugins or scripts from directories such as ``.claude``, and some of
that is code that runs at start-up. A repository under review could use
such files to give the runner instructions of its own.

Runners differ in which files they read and in whether that can be
switched off. So the worktree is filtered before any runner sees it:
every file and directory with one of these names is removed.

The rule goes by name only. A file with one of these names is removed
whatever it contains. Reading a file to decide whether it is an
instruction is exactly the judgement this rule is there to avoid.
"""

from collections.abc import Iterable

#: Names of files that some runner reads as instructions.
INSTRUCTION_FILES = frozenset(
    {
        "CLAUDE.md",
        "CLAUDE.local.md",
        "AGENTS.md",
        "AGENTS.override.md",
        "GEMINI.md",
        "REVIEW.md",
        # Cursor's older rules file, which it still reads.
        ".cursorrules",
        ".mcp.json",
        "opencode.json",
        "opencode.jsonc",
    }
)

#: Paths whose contents some runner loads: settings, hooks, plugins,
#: skills, commands. Most are directories.
INSTRUCTION_DIRECTORIES = frozenset(
    {
        ".claude",
        ".codex",
        ".opencode",
        ".agents",
        ".cursor",
        ".gemini",
        ".github/copilot-instructions.md",
    }
)


def instructs(path: str) -> bool:
    """Whether ``path``, relative to the top of a worktree, is one a
    runner might read as instructions.

    The names are matched at any depth. A runner looks in the directories
    above the one it works in, so a file in a subdirectory can reach it
    as well as one at the top.
    """
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    if not parts:
        return False
    if parts[-1] in INSTRUCTION_FILES:
        return True
    for directory in INSTRUCTION_DIRECTORIES:
        needle = [part for part in directory.split("/") if part]
        if any(
            parts[index : index + len(needle)] == needle
            for index in range(len(parts) - len(needle) + 1)
        ):
            return True
    return False


def instruction_sources(paths: Iterable[str]) -> tuple[str, ...]:
    """The paths among ``paths`` that a runner might read as
    instructions, sorted."""
    return tuple(sorted(path for path in paths if instructs(path)))
