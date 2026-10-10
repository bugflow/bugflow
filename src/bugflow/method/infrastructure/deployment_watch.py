"""Stop a program when a deployment other than the one it started with
is put in force.

A worker reads its reviewers once, when it starts. It runs
``stop_on_new_deployment`` as a background task, and shuts down when a
different deployment is in force; the container's restart policy starts
it again, and the new start reads the new deployment.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from bugflow.method.domain.models.policy_deployment import PutInForce
from bugflow.method.domain.repositories.policy_deployment import (
    PolicyDeploymentRepository,
)

#: Seconds between two checks for a newer deployment.
DEPLOYMENT_POLL_SECONDS = 15.0


@dataclass(frozen=True, kw_only=True)
class DeployedFrom:
    """Which deployment a program's reviewers were built from."""

    repository: str
    commit: str
    content_hash: str


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


async def wait_for_new_deployment(
    started_with: DeployedFrom | None,
    deployments: PolicyDeploymentRepository,
    interval: float = DEPLOYMENT_POLL_SECONDS,
    warn: Callable[[str], None] = print,
    stopping: asyncio.Event | None = None,
) -> PutInForce | None:
    """Return the deployment in force once it is not ``started_with``.

    Asks the database every ``interval`` seconds. A failed query is
    reported through ``warn`` and tried again at the next interval, so
    a database that is briefly unreachable does not stop the program.

    ``stopping`` is an event the caller sets when the program is
    shutting down for another reason. When it is set this returns None
    without another query.
    """
    stopping = stopping or asyncio.Event()
    while True:
        # Wait for the interval, or less if the program starts stopping.
        try:
            await asyncio.wait_for(stopping.wait(), timeout=interval)
        except TimeoutError:
            pass
        else:
            return None
        try:
            latest = await asyncio.to_thread(deployments.last_put_in_force)
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
) -> None:
    """Call ``stop`` once a deployment other than ``started_with`` is in
    force, after saying which one. Run as a background task.

    Returns without calling ``stop`` if ``stopping`` is set first.
    """
    latest = await wait_for_new_deployment(
        started_with, deployments, interval, warn=say, stopping=stopping
    )
    if latest is None:
        return
    say(
        f"deployment {latest.repository} at {latest.commit} is in force; "
        "stopping so the next start reads it"
    )
    stop()
