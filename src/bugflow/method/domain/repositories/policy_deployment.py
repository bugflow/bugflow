"""The interface that keeps the deployments this server was sent.

One interface keeps them and says which is in force, because being in
force is a fact about a deployment and nothing else holds it. Each
deployment put in force is also recorded as ``policies.deployed`` in
the journal, which is where its history is read.
"""

from collections.abc import Callable, Sequence
from typing import Protocol

from bugflow.method.domain.models.policy_deployment import (
    PolicyDeployment,
    PutInForce,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.repositories.base import BaseRepository

#: The facts that record a deployment put in force, given the deployment
#: it replaced, or None for the server's first.
Facts = Callable[[PutInForce | None], Sequence[JournalEntry]]


class PolicyDeploymentRepository(BaseRepository[PolicyDeployment], Protocol):
    def deploy(
        self, deployment: PolicyDeployment, facts: Facts = lambda _: ()
    ) -> bool:
        """Keep the deployment and put it in force, and record ``facts``
        in the journal in the same transaction, so a deployment is never
        in force without them.

        Returns whether anything changed. Sending the deployment already
        in force changes nothing and records nothing, so a sender may
        repeat itself. Sending one held earlier puts it back in force.

        Raises ``PolicyDeploymentConflictError`` if that repository and
        commit are held with other content: a commit names one
        deployment, and the one in force stands.
        """
        ...

    def in_force(self) -> PolicyDeployment | None:
        """The deployment put in force last, or None on a server that
        was never sent one, which reviews nothing."""
        ...

    def last_put_in_force(self) -> PutInForce | None:
        """The names of the deployment in force and when it was put,
        without its files, or None if there is none. For a caller that
        only asks whether the deployment in force has changed."""
        ...
