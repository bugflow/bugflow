"""A runner that does no work, for tests and for a server with no
runner configured.

Every task it is given ends at once with the outcome "declined" and no
answer. A caller's steps all run, and the journal records a run, but no
directory is read and no model is called.
"""

import hashlib
import inspect
import sys

from bugflow.work.domain.models.agent import AgentHandle, AgentRun, AgentTask

RUNNER = "stub"


class StubAgent:
    @property
    def runner(self) -> str:
        return RUNNER

    @property
    def fingerprint(self) -> str:
        """A hash of this module's source, since nothing else decides
        how the stub behaves."""
        source = inspect.getsource(sys.modules[__name__])
        return hashlib.sha256(source.encode()).hexdigest()[:12]

    def dispatch(self, task: AgentTask) -> AgentHandle:
        return AgentHandle(
            runner=RUNNER,
            fingerprint=self.fingerprint,
            run=AgentRun(
                outcome="declined",
                runner=RUNNER,
                fingerprint=self.fingerprint,
                detail="no runner is configured, so nothing was dispatched",
            ),
        )

    @property
    def notifies(self) -> bool:
        return False

    def wait(self, handle: AgentHandle, patience: float) -> bool:
        """Return at once: the run finished inside ``dispatch``."""
        return True

    def collect(self, handle: AgentHandle) -> AgentRun:
        """Return the run the handle carries."""
        return handle.run or AgentRun(
            outcome="failed",
            runner=RUNNER,
            fingerprint=self.fingerprint,
            detail="a stub handle with no run in it",
        )

    def stop(self, handle: AgentHandle) -> None:
        """Do nothing: the run finished inside ``dispatch``."""
