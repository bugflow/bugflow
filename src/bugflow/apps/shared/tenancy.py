"""Which tenant a program serves, and which others the ingress reaches
(ADR 011).

A tenant is an area of responsibility with a worker of its own on the
server (ADR 010). Each has a policy deployment in force of its own, and
a worker reads its tenant's. The setting ``TENANT`` names it; a server
with one tenant leaves it unset, and the tenant is ``default``.

The ingress is one for the whole server. Its own tenant is ``TENANT``,
in its own namespace and on its own task queue; ``TENANTS`` lists the
others and where each one's worker is, so a delivery reaches every
tenant whose gnome judges the repository.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from bugflow.method.domain.errors import PolicyDeploymentError
from bugflow.method.domain.models.policy_deployment import (
    DEFAULT_TENANT,
    checked_tenant,
)

#: The setting that names the tenant a program serves.
TENANT_VARIABLE = "TENANT"

#: The setting that lists the other tenants the ingress reaches, as
#: ``tenant=namespace/task-queue`` separated by commas.
TENANTS_VARIABLE = "TENANTS"


def tenant_from(environ: Mapping[str, str]) -> str:
    """Read the tenant ``TENANT`` names, or ``default`` where it is
    unset. Raises ``ValueError`` for a name that is no tenant's."""
    name = environ.get(TENANT_VARIABLE, "").strip() or DEFAULT_TENANT
    try:
        return checked_tenant(name)
    except PolicyDeploymentError as exc:
        raise ValueError(f"{TENANT_VARIABLE} is {exc}") from exc


@dataclass(frozen=True, kw_only=True)
class Tenant:
    """Where one tenant's worker is: the Temporal namespace it runs in
    and the task queue it listens on."""

    name: str
    namespace: str
    task_queue: str


def tenants_from(environ: Mapping[str, str]) -> tuple[Tenant, ...]:
    """Read the other tenants ``TENANTS`` lists, in the order listed.

    Each is ``tenant=namespace/task-queue``. Raises ``ValueError`` for an
    entry that is not one, for a tenant listed twice, and for the
    program's own tenant, whose namespace and queue are its own
    settings.
    """
    own = tenant_from(environ)
    found: dict[str, Tenant] = {}
    for entry in environ.get(TENANTS_VARIABLE, "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        name, equals, where = entry.partition("=")
        namespace, slash, task_queue = where.partition("/")
        name, namespace, task_queue = (
            name.strip(),
            namespace.strip(),
            task_queue.strip(),
        )
        if not (equals and slash and name and namespace and task_queue):
            raise ValueError(
                f"{entry!r} is not tenant=namespace/task-queue; "
                f"{TENANTS_VARIABLE} says where each other tenant's worker "
                "is"
            )
        try:
            checked_tenant(name)
        except PolicyDeploymentError as exc:
            raise ValueError(f"{TENANTS_VARIABLE} names {exc}") from exc
        if name == own:
            raise ValueError(
                f"{TENANTS_VARIABLE} names {name}, which is this program's "
                f"own tenant; its namespace and task queue are its own "
                "settings"
            )
        if name in found:
            raise ValueError(f"{TENANTS_VARIABLE} names {name} twice")
        found[name] = Tenant(
            name=name, namespace=namespace, task_queue=task_queue
        )
    return tuple(found.values())
