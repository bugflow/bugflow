"""The interface that keeps the deployments this server was sent.

One interface keeps them and says which is in force, because being in
force is a fact about a deployment and nothing else holds it. The
listing is part of the interface from the start: a store that can be
written and read by key but not listed has to be worked around before
a page can show it.
"""

from typing import Protocol

from bugflow.method.domain.models.policy_deployment import (
    PolicyDeployment,
    PutInForce,
)
from bugflow.shared.domain.repositories.base import BaseRepository


class PolicyDeploymentRepository(BaseRepository[PolicyDeployment], Protocol):
    def deploy(self, deployment: PolicyDeployment) -> bool:
        """Keep the deployment and put it in force.

        Returns whether anything changed. Sending the deployment already
        in force changes nothing, so a sender may repeat itself. Sending
        one held earlier puts it back in force.

        Raises ``PolicyDeploymentConflictError`` if that repository and
        commit are held with other content: a commit names one
        deployment, and the one in force stands.
        """
        ...

    def in_force(self) -> PolicyDeployment | None:
        """The deployment put in force last, or None on a server that
        was never sent one, which reviews nothing."""
        ...

    def held(self, repository: str, commit: str) -> PolicyDeployment | None:
        """The deployment that repository and commit name, or None."""
        ...

    def last_put_in_force(self) -> PutInForce | None:
        """The names of the deployment in force and when it was put,
        without its files, or None if there is none. For a caller that
        only asks whether the deployment in force has changed."""
        ...

    def history(self) -> list[PutInForce]:
        """Each time a deployment was put in force, the latest first."""
        ...
