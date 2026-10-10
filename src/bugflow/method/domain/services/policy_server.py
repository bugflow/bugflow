"""The interface to a server that takes deployments."""

from typing import Protocol

from bugflow.method.domain.models.policy_deployment import PolicyDeployment
from bugflow.method.domain.values.server_answer import ServerAnswer


class PolicyServerService(Protocol):
    def send(
        self, deployment: PolicyDeployment, check_only: bool
    ) -> ServerAnswer:
        """Send the deployment to be put in force, or with ``check_only``
        to be parsed and not stored.

        Raises ``PoliciesRefusedError`` if the server refuses the files,
        and ``PolicyServerError`` if the call could not be made or was
        not allowed.
        """
        ...
