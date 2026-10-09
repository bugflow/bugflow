"""The interface for passing a completion on to whatever is waiting for
the run."""

from typing import Protocol

from bugflow.shared.domain.values.acknowledgement import Acknowledgement
from bugflow.shared.domain.values.correlation import Correlation


class CompletionHandler(Protocol):
    """A use case works out which workflow run dispatched the finished
    work, and calls this. What happens next is decided by the program
    that supplies the handler. A server that runs workflows sends a
    signal to the waiting workflow run."""

    def handle_completion(
        self, correlation: Correlation, agent_id: str, remote_id: str
    ) -> Acknowledgement:
        """Tell the workflow run that this agent's run has finished.

        Answers "wilco" if something was waiting for it. Answers
        "unable" if nothing was: the workflow run had already ended, and
        a completion that arrives after that changes nothing.
        """
        ...
