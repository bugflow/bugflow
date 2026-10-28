"""The deployments this server was sent, kept in memory, for tests."""

from collections.abc import Callable
from datetime import UTC, datetime

from bugflow.method.domain.errors import PolicyDeploymentConflictError
from bugflow.method.domain.models.policy_deployment import (
    PolicyDeployment,
    PutInForce,
)
from bugflow.method.domain.repositories.policy_deployment import Facts
from bugflow.shared.domain.services.recording import RecordingService


class InMemoryPolicyDeployments:
    """Implements ``PolicyDeploymentRepository`` in a dictionary and a
    list. ``now`` is asked for the time each deployment is put in force,
    and ``journal`` records its facts.
    """

    def __init__(
        self,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        journal: RecordingService | None = None,
    ) -> None:
        self._now = now
        self._journal = journal
        self._held: dict[tuple[str, str], PolicyDeployment] = {}
        self._put: list[PutInForce] = []

    def deploy(
        self, deployment: PolicyDeployment, facts: Facts = lambda _: ()
    ) -> bool:
        key = (deployment.repository, deployment.commit)
        earlier = self._held.get(key)
        if (
            earlier is not None
            and earlier.content_hash != deployment.content_hash
        ):
            raise PolicyDeploymentConflictError(*key)
        latest = self._put[-1] if self._put else None
        if latest and (latest.repository, latest.commit) == key:
            self._held[key] = deployment
            return False
        # Recorded before anything is changed, so a journal that refuses
        # leaves the deployment unchanged, as a transaction would.
        recorded = facts(latest)
        if recorded:
            if self._journal is None:
                raise ValueError(
                    "this store has no journal to record the "
                    "deployment's facts in"
                )
            self._journal.append(recorded)
        self._held[key] = deployment
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
