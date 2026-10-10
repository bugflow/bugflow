"""Policy deployment access by one role at the identity provider.

A policy repository's pipeline is a client at the identity provider
holding a role that may deploy policies and do nothing else. The role's
name is a setting, given at construction.
"""

from dataclasses import dataclass

from bugflow.shared.domain.values.caller import Caller


@dataclass(frozen=True)
class RolePolicyDeploymentAccess:
    """Implements ``PolicyDeploymentAccessService``: a caller holding
    ``role`` may deploy."""

    role: str

    def may_deploy(self, caller: Caller) -> bool:
        return self.role in caller.roles
