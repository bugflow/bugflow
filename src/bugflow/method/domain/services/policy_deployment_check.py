"""The interface for checking that a deployment can be read.

A deployment is checked before it is stored, so one with a file that
does not parse is never put in force. The parse is done by an adapter,
which the application supplies.
"""

from typing import Protocol

from bugflow.method.domain.models.policy_deployment import PolicyDeployment


class PolicyDeploymentCheckService(Protocol):
    def check(self, deployment: PolicyDeployment) -> None:
        """Return if every file of the deployment parses.

        Raises ``PolicyDeploymentError`` naming every problem found.
        """
        ...
