"""Run a command and return its exit code and output.

An adapter that needs a program such as git takes a function of the
``RunCommand`` shape. In the running server that function is
``run_command``. A test passes its own, and no process is started.
"""

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Completed:
    """A command's exit code and what it wrote."""

    returncode: int
    stdout: str
    stderr: str


class RunCommand(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        cwd: str | None,
        env: Mapping[str, str],
        timeout: float,
    ) -> Completed:
        """Run ``argv`` in directory ``cwd`` with exactly the
        environment ``env``, for at most ``timeout`` seconds."""
        ...


def run_command(
    argv: Sequence[str],
    cwd: str | None,
    env: Mapping[str, str],
    timeout: float,
) -> Completed:
    """Run the command as a child process. A command that exits with an
    error is returned, not raised."""
    result = subprocess.run(
        list(argv),
        cwd=cwd,
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return Completed(result.returncode, result.stdout, result.stderr)
