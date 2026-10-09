"""Prepare a worktree with git: fetch one commit of a repository into a
directory and make it safe for a runner to read.

``prepare`` does four things, in this order:

1. Fetch the commit under review, and the base commit if one is given,
   each without its history. The base is the commit the forge reports
   for the pull request, not the base branch. A branch moves on, and a
   comparison with where it is now would show other people's later
   changes as part of this pull request.
2. Check the commit out.
3. Make the ``.git`` directory harmless. Its hooks are deleted, because
   a hook is a script that git runs, and the runner will run git. Its
   configuration is replaced with the minimum, so that it holds no
   address of a remote and no token. The stored objects stay, so
   ``git diff`` against the base still works.
4. Remove the files a runner might read as instructions, and report
   which were removed.

The token is given to git through environment variables that set the
``http.extraHeader`` option for one command. It is never part of a URL,
which git would write into the configuration, and never an argument,
which other processes on the machine can see while the command runs. It
is sent as HTTP Basic with the user ``x-access-token``. GitHub accepts a
token in that form for git, and does not accept ``Bearer``.
"""

import base64
import os
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.work.domain.errors import WorktreeUnavailableError
from bugflow.work.infrastructure.commands import (
    Completed,
    RunCommand,
    run_command,
)
from bugflow.work.infrastructure.worktree import strip_instruction_sources

#: The name of the branch that ``prepare`` gives the base commit, so
#: that a runner can run ``git diff review-base HEAD`` with no remote.
BASE_REF = "review-base"


class GitWorktree:
    def __init__(
        self,
        clone_url: str,
        token: str = "",
        binary: str = "git",
        timeout: float = 600.0,
        run: RunCommand = run_command,
    ) -> None:
        """``clone_url`` is the address repositories are fetched from,
        such as ``https://forge.example``. The owner and repository are
        added to it. ``token`` is sent with each fetch, if given.
        ``timeout`` is the longest one git command may take, in
        seconds."""
        self._clone_url = clone_url.rstrip("/")
        self._token = token
        self._binary = binary
        self._timeout = timeout
        self._run = run

    def _git(
        self,
        argv: Sequence[str],
        cwd: Path,
        extra: Mapping[str, str] | None = None,
    ) -> Completed:
        """Run one git command. Raises ``WorktreeUnavailableError`` with
        git's message if it fails."""
        environment = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/nonexistent",
            # Never ask for a password. Nobody is there to answer, and
            # the command would wait until its timeout.
            "GIT_TERMINAL_PROMPT": "0",
            # Ignore the configuration of the user and of the machine.
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            **(extra or {}),
        }
        completed = self._run(
            [self._binary, *argv], str(cwd), environment, self._timeout
        )
        if completed.returncode != 0:
            raise WorktreeUnavailableError(
                (completed.stderr or completed.stdout).strip()
                or f"git {argv[0]} failed"
            )
        return completed

    def url_for(self, ref: PullRequestRef) -> str:
        """The address the pull request's repository is fetched from."""
        return f"{self._clone_url}/{ref.owner}/{ref.repo}.git"

    def prepare(
        self,
        ref: PullRequestRef,
        head_sha: str,
        into: Path,
        base_sha: str = "",
    ) -> tuple[str, ...]:
        if not head_sha:
            raise WorktreeUnavailableError("no head commit to lay out")
        # Only the owner may read the directory: it may be under a
        # temporary directory that every account on the machine can
        # reach. The mode is set with chmod after mkdir, because mkdir
        # applies the umask to its mode and does nothing at all to a
        # directory that already exists.
        into.mkdir(parents=True, exist_ok=True)
        os.chmod(into, 0o700)
        self._git(["init", "--quiet"], into)
        self._fetch(self.url_for(ref), head_sha, into)
        self._git(["checkout", "--quiet", "FETCH_HEAD"], into)
        if base_sha:
            self._fetch(self.url_for(ref), base_sha, into)
            self._git(
                ["branch", "--quiet", "--force", BASE_REF, "FETCH_HEAD"],
                into,
            )
        self._disarm(into / ".git")
        return strip_instruction_sources(into)

    def keep_default_branch(self, owner: str, repo: str, into: Path) -> str:
        """Replace the directory ``into`` with the latest commit of the
        repository's default branch, and return that commit's id.

        The commit is fetched into a directory beside ``into`` and then
        moved into place. If the fetch fails, ``into`` is left as it
        was. The ``.git`` directory is made harmless as in ``prepare``.
        Instruction files are not removed.
        """
        # A remote's HEAD is its default branch.
        return self._keep(owner, repo, "HEAD", into)

    def keep_commit(self, owner: str, repo: str, sha: str, into: Path) -> str:
        """Replace the directory ``into`` with one commit of the
        repository, and return that commit's id. Otherwise the same as
        ``keep_default_branch``."""
        return self._keep(owner, repo, sha, into)

    def _keep(self, owner: str, repo: str, what: str, into: Path) -> str:
        incoming = into.with_name(f".{into.name}.incoming")
        previous = into.with_name(f".{into.name}.previous")
        for stale in (incoming, previous):
            shutil.rmtree(stale, ignore_errors=True)
        incoming.mkdir(parents=True)
        self._git(["init", "--quiet"], incoming)
        self._fetch(f"{self._clone_url}/{owner}/{repo}.git", what, incoming)
        self._git(["checkout", "--quiet", "FETCH_HEAD"], incoming)
        commit = self._git(["rev-parse", "HEAD"], incoming).stdout.strip()
        self._disarm(incoming / ".git")
        if into.exists():
            into.rename(previous)
        incoming.rename(into)
        shutil.rmtree(previous, ignore_errors=True)
        return commit

    def _fetch(self, url: str, what: str, into: Path) -> None:
        """Fetch one commit, without its history, sending the token."""
        self._git(
            ["fetch", "--depth", "1", "--quiet", url, what],
            into,
            credential_environment(self._token),
        )

    def _disarm(self, git: Path) -> None:
        """Delete a ``.git`` directory's hooks and replace its
        configuration with the minimum."""
        if not git.is_dir():
            return
        hooks = git / "hooks"
        if hooks.is_symlink():
            hooks.unlink()
        shutil.rmtree(hooks, ignore_errors=True)
        (git / "config").write_text(
            "[core]\n\trepositoryformatversion = 0\n\tbare = false\n"
        )


def credential_environment(token: str) -> dict[str, str]:
    """The environment variables that make git send ``token`` with its
    requests. Empty if there is no token."""
    if not token:
        return {}
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
    }
