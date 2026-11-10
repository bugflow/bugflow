"""Policy deployment access by one role at the identity provider, and
for a tenant that names its deployer, by that client.

A policy repository's pipeline is a client at the identity provider
holding a role that may deploy policies and do nothing else. The role's
name is a setting, given at construction. A server with several tenants
names each tenant's pipeline client too (ADR 011), so one tenant's
pipeline cannot put a deployment in force for another; a tenant named
no client takes any caller with the role.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from bugflow.shared.domain.values.caller import Caller


@dataclass(frozen=True)
class RolePolicyDeploymentAccess:
    """Implements ``PolicyDeploymentAccessService``: a caller holding
    ``role`` may deploy, to a tenant in ``deployers`` only as the client
    it names."""

    role: str
    #: By tenant: the id of the client that deploys that tenant's
    #: policies.
    deployers: Mapping[str, str] = field(default_factory=dict)

    def may_deploy(self, caller: Caller, tenant: str) -> bool:
        if self.role not in caller.roles:
            return False
        named = self.deployers.get(tenant)
        return named is None or named == caller.client


def deployers_from(listed: str) -> dict[str, str]:
    """Read each tenant's deploying client from ``tenant=client`` pairs
    separated by commas, as the setting ``TENANT_DEPLOYERS`` lists them.

    Raises ``ValueError`` for a pair that is not one.
    """
    found: dict[str, str] = {}
    for pair in listed.split(","):
        pair = pair.strip()
        if not pair:
            continue
        tenant, equals, client = pair.partition("=")
        if not equals or not tenant.strip() or not client.strip():
            raise ValueError(
                f"{pair!r} is not tenant=client; TENANT_DEPLOYERS names "
                "the client that deploys each tenant's policies"
            )
        found[tenant.strip()] = client.strip()
    return found
