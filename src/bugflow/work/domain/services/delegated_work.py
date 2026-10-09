"""The interface to a runner: hand it a task, wait for it, read what it
produced, stop it.

Every kind of runner is used through this one interface, whether it is a
hosted model or a person working with a coding agent. The interface
says nothing about what the task is for.
"""

from typing import Protocol

from bugflow.work.domain.models.agent import AgentHandle, AgentRun, AgentTask


class DelegatedWorkService(Protocol):
    @property
    def runner(self) -> str:
        """The runner's name, as the configuration gives it."""
        ...

    @property
    def fingerprint(self) -> str:
        """A hash of the settings that decide how the runner behaves.
        Two runs with the same fingerprint were set up the same way."""
        ...

    def dispatch(self, task: AgentTask) -> AgentHandle:
        """Start the task and return a handle to the run.

        A runner that finishes before this returns puts the finished run
        in the handle. One that carries on working puts its own name for
        the work there. The adapter keeps nothing in memory between
        calls: a later call is given the handle.

        Raises ``AgentUnavailableError`` only if no run was started. A
        run that started and then got nowhere is not an error; it is
        read with ``collect``.
        """
        ...

    @property
    def notifies(self) -> bool:
        """True if a completion will arrive when a run finishes, so
        that nothing has to call ``wait``.

        False for a runner that has to be asked. Also False for a runner
        that could send completions but is not set up to send them here.
        """
        ...

    def wait(self, handle: AgentHandle, patience: float) -> bool:
        """Wait up to ``patience`` seconds for the run to have something
        new to read.

        Returns True if there is something to read, False if the time
        ran out. Either way the caller reads with ``collect``: a run
        that is not finished still has a state worth recording.

        How to wait is up to the adapter. A runner that finished inside
        ``dispatch`` answers at once. Another may hold a connection
        open, or ask the runner again every so often.
        """
        ...

    def collect(self, handle: AgentHandle) -> AgentRun:
        """Return the run as it stands, whatever its outcome. A run that
        stopped short or failed is returned, not raised."""
        ...

    def stop(self, handle: AgentHandle) -> None:
        """End the run, so that it does no more work and costs no more.

        Stopping a run twice, or a run that has already finished, does
        nothing.
        """
        ...
