"""Stop a program when a deployment other than the one it started with
is put in force.

A worker reads its tenant's reviewers once, when it starts. It runs
``stop_on_new_deployment`` as a background task, and shuts down when a
different deployment is in force for its tenant; the container's
restart policy starts it again, and the new start reads the new
deployment. The ingress serves every tenant, so it runs
``stop_on_new_deployments`` instead, which watches them all.
"""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from opentelemetry.instrumentation.utils import suppress_instrumentation

from bugflow.method.domain.models.policy_deployment import (
    DEFAULT_TENANT,
    PutInForce,
)
from bugflow.method.domain.repositories.policy_deployment import (
    PolicyDeploymentRepository,
)

#: Seconds between two checks for a newer deployment.
DEPLOYMENT_POLL_SECONDS = 15.0


@dataclass(frozen=True, kw_only=True)
class DeployedFrom:
    """Which deployment a program's reviewers were built from, and
    whose."""

    repository: str
    commit: str
    content_hash: str
    tenant: str = DEFAULT_TENANT


def changed_since(
    started_with: DeployedFrom | None, latest: PutInForce | None
) -> bool:
    """Whether the deployment in force is not the one a program started
    with.

    ``started_with`` is None for a program that started with no
    deployment. ``latest`` is None if the database holds none.
    """
    if latest is None:
        return False
    if started_with is None:
        return True
    return (latest.repository, latest.commit) != (
        started_with.repository,
        started_with.commit,
    )


def untraced_check(
    deployments: PolicyDeploymentRepository, tenant: str = DEFAULT_TENANT
) -> PutInForce | None:
    """The deployment last put in force for the tenant, read with no
    trace of the query.

    A check runs every few seconds outside any request or workflow, so
    each traced query would be a trace of its own.
    """
    with suppress_instrumentation():
        return deployments.last_put_in_force(tenant)


def untraced_checks(
    deployments: PolicyDeploymentRepository,
) -> dict[str, PutInForce]:
    """Every tenant's deployment last put in force, by tenant, read with
    no trace of the queries."""
    with suppress_instrumentation():
        found = {}
        for tenant in deployments.tenants():
            latest = deployments.last_put_in_force(tenant)
            if latest is not None:
                found[tenant] = latest
        return found


async def _wait(stopping: asyncio.Event, interval: float) -> bool:
    """Wait for the interval, or less if the program starts stopping.
    True when it did."""
    try:
        await asyncio.wait_for(stopping.wait(), timeout=interval)
    except TimeoutError:
        return False
    return True


async def wait_for_new_deployment(
    started_with: DeployedFrom | None,
    deployments: PolicyDeploymentRepository,
    interval: float = DEPLOYMENT_POLL_SECONDS,
    warn: Callable[[str], None] = print,
    stopping: asyncio.Event | None = None,
    tenant: str = DEFAULT_TENANT,
) -> PutInForce | None:
    """Return the tenant's deployment in force once it is not
    ``started_with``.

    Asks the database every ``interval`` seconds. A failed query is
    reported through ``warn`` and tried again at the next interval, so
    a database that is briefly unreachable does not stop the program.

    ``stopping`` is an event the caller sets when the program is
    shutting down for another reason. When it is set this returns None
    without another query.
    """
    stopping = stopping or asyncio.Event()
    while True:
        if await _wait(stopping, interval):
            return None
        try:
            latest = await asyncio.to_thread(
                untraced_check, deployments, tenant
            )
        except Exception as exc:
            warn(f"warning: could not check for a new deployment: {exc}")
            continue
        if latest is not None and changed_since(started_with, latest):
            return latest


async def stop_on_new_deployment(
    stop: Callable[[], None],
    started_with: DeployedFrom | None,
    deployments: PolicyDeploymentRepository,
    interval: float = DEPLOYMENT_POLL_SECONDS,
    say: Callable[[str], None] = print,
    stopping: asyncio.Event | None = None,
    tenant: str = DEFAULT_TENANT,
) -> None:
    """Call ``stop`` once a deployment other than ``started_with`` is in
    force for the tenant, after saying which one. Run as a background
    task.

    Returns without calling ``stop`` if ``stopping`` is set first.
    """
    latest = await wait_for_new_deployment(
        started_with,
        deployments,
        interval,
        warn=say,
        stopping=stopping,
        tenant=tenant,
    )
    if latest is None:
        return
    say(
        f"deployment {latest.repository} at {latest.commit} is in force "
        f"for {latest.tenant}; stopping so the next start reads it"
    )
    stop()


def tenants_changed_since(
    started_with: Mapping[str, DeployedFrom],
    latest: Mapping[str, PutInForce],
) -> bool:
    """Whether any tenant's deployment in force is not the one a program
    started with, or a tenant has a deployment the program started
    without.

    A tenant the program started with and the database no longer lists
    is no change: a deployment put in force is never withdrawn, so that
    does not happen.
    """
    return any(
        changed_since(started_with.get(tenant), put)
        for tenant, put in latest.items()
    )


async def stop_on_new_deployments(
    stop: Callable[[], None],
    started_with: Mapping[str, DeployedFrom],
    deployments: PolicyDeploymentRepository,
    interval: float = DEPLOYMENT_POLL_SECONDS,
    say: Callable[[str], None] = print,
    stopping: asyncio.Event | None = None,
) -> None:
    """Call ``stop`` once any tenant's deployment in force is not the
    one in ``started_with``, after saying which. For the program that
    serves every tenant. Run as a background task.

    Returns without calling ``stop`` if ``stopping`` is set first.
    """
    stopping = stopping or asyncio.Event()
    while True:
        if await _wait(stopping, interval):
            return
        try:
            latest = await asyncio.to_thread(untraced_checks, deployments)
        except Exception as exc:
            say(f"warning: could not check for a new deployment: {exc}")
            continue
        if tenants_changed_since(started_with, latest):
            break
    changed = sorted(
        tenant
        for tenant, put in latest.items()
        if changed_since(started_with.get(tenant), put)
    )
    for tenant in changed:
        put = latest[tenant]
        say(
            f"deployment {put.repository} at {put.commit} is in force for "
            f"{tenant}; stopping so the next start reads it"
        )
    stop()
