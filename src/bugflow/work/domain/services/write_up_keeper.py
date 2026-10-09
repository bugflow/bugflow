"""The interface for storing a run's write-up."""

from typing import Protocol

from bugflow.shared.domain.values.correlation import Correlation


class WriteUpKeeperService(Protocol):
    def keep(self, correlation: Correlation, agent_id: str, text: str) -> str:
        """Store the write-up for this workflow run and agent, and
        return the key it is stored under.

        The key depends only on the workflow run and the agent. Storing
        a write-up for the same pair again keeps what is already there
        and returns the same key.

        Raises ``WriteUpNotKeptError`` if the write-up is not stored. A
        write-up that is empty, or only white space, is not stored.
        """
        ...
