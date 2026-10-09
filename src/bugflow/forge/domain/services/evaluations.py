"""The interface for passing a pull request's deliveries on to its
evaluation.

In a running server each open pull request has a workflow that collects
its deliveries and runs evaluations. In a test the delivery may be
evaluated on the spot. Either way the caller is told which workflow run
took the delivery.
"""

from typing import Protocol

from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class EvaluationStarterPort(Protocol):
    def start(self, ref: PullRequestRef, delivery_id: str) -> Correlation:
        """Pass the delivery to the pull request's workflow, starting the
        workflow if it is not running. Raises ``EvaluationStartError`` if
        that cannot be done."""
        ...

    def close(
        self, ref: PullRequestRef, delivery_id: str, merged: bool = False
    ) -> Correlation | None:
        """Tell the pull request's workflow that the pull request has
        closed, and whether it was merged. A merged pull request is
        evaluated one last time; an abandoned one is not.

        Returns None if no workflow was running for it.
        """
        ...
