"""The interface for reading a deployment's files from where they are
kept."""

from typing import Protocol

from bugflow.method.domain.models.policy_deployment import PolicyDeployment


class PolicyFilesService(Protocol):
    def read(self, repository: str, commit: str) -> PolicyDeployment:
        """The files, as a deployment with the given repository and
        commit. Raises ``PolicyDeploymentError`` if they are not a
        deployment."""
        ...
