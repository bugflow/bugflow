"""The deployments this server was sent, kept in memory, for tests."""

from collections.abc import Callable
from datetime import UTC, datetime

from bugflow.method.domain.errors import PolicyDeploymentConflictError
from bugflow.method.domain.models.policy_deployment import (
    PolicyDeployment,
    PutInForce,
)


class InMemoryPolicyDeployments:
    """Implements ``PolicyDeploymentRepository`` in a dictionary and a
    list. ``now`` is asked for the time each deployment is put in force.
    """

    def __init__(
        self, now: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._now = now
        self._held: dict[tuple[str, str], PolicyDeployment] = {}
        self._put: list[PutInForce] = []

    def deploy(self, deployment: PolicyDeployment) -> bool:
        key = (deployment.repository, deployment.commit)
        earlier = self._held.get(key)
        if (
            earlier is not None
            and earlier.content_hash != deployment.content_hash
        ):
            raise PolicyDeploymentConflictError(*key)
        self._held[key] = deployment
        latest = self._put[-1] if self._put else None
        if latest and (latest.repository, latest.commit) == key:
            return False
        self._put.append(
            PutInForce(
                repository=deployment.repository,
                commit=deployment.commit,
                content_hash=deployment.content_hash,
                at=self._now(),
            )
        )
        return True

    def in_force(self) -> PolicyDeployment | None:
        if not self._put:
            return None
        latest = self._put[-1]
        return self._held[(latest.repository, latest.commit)]

    def held(self, repository: str, commit: str) -> PolicyDeployment | None:
        return self._held.get((repository, commit))

    def last_put_in_force(self) -> PutInForce | None:
        return self._put[-1] if self._put else None

    def history(self) -> list[PutInForce]:
        return list(reversed(self._put))
