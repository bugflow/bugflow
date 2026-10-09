"""The interface to a runner, as this context uses it.

The work context has an interface for the same thing. This one is this
context's own and uses its own types, so that this context imports
nothing from that one. An application connects the two.
"""

from typing import Protocol

from bugflow.review.domain.models.delegation import Handle, Run, Task


class DelegatedWorkService(Protocol):
    @property
    def runner(self) -> str:
        """The runner's name, as the configuration gives it."""
        ...

    @property
    def fingerprint(self) -> str:
        """A hash of the settings that decide how the runner behaves."""
        ...

    def dispatch(self, task: Task) -> Handle:
        """Start the task and return a handle to the run.

        Raises ``AgentUnavailableError`` only if no run was started.
        """
        ...

    @property
    def notifies(self) -> bool:
        """True if a completion will arrive when a run finishes, so
        that nothing has to call ``wait``."""
        ...

    def wait(self, handle: Handle, patience: float) -> bool:
        """Wait up to ``patience`` seconds for the run to have something
        new to read. Returns True if it has, False if the time ran
        out."""
        ...

    def collect(self, handle: Handle) -> Run:
        """Return the run as it stands, whatever its outcome."""
        ...

    def stop(self, handle: Handle) -> None:
        """End the run, so that it does no more work."""
        ...
