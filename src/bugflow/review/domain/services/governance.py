"""The interface for asking which reviewers govern a repository."""

from typing import Protocol


class GovernanceService(Protocol):
    def governing_agents(self, forge: str, repo: str) -> frozenset[str]:
        """Return the agent ids of the reviewers whose verdicts decide
        the repository's label.

        A reviewer that is not in the set still reviews and still
        comments. Its verdict cannot hold a pull request at
        "review:wip" or move it to "review:escalate".
        """
        ...
