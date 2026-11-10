"""The interface for asking whether a caller may deploy policies to this
server, for one tenant.

Whoever may deploy chooses the reviewers' instructions, because the
server cannot check what it is sent against the policy repository. So
the decision is behind an interface of its own, apart from any other
access a caller has. It is asked for a tenant, because each tenant's
pipeline deploys that tenant's policies and nobody else's (ADR 011).
"""

from typing import Protocol

from bugflow.shared.domain.values.caller import Caller


class PolicyDeploymentAccessService(Protocol):
    def may_deploy(self, caller: Caller, tenant: str) -> bool:
        """Whether ``caller`` may send a policy deployment for the
        tenant, or ask for one to be checked."""
        ...
