"""The deployments this server was sent, kept in memory, for tests."""

from collections.abc import Callable
from datetime import UTC, datetime

from bugflow.method.domain.errors import PolicyDeploymentConflictError
from bugflow.method.domain.models.policy_deployment import (
    DEFAULT_TENANT,
    PolicyDeployment,
    PutInForce,
)
from bugflow.method.domain.repositories.policy_deployment import Facts
from bugflow.shared.domain.services.recording import RecordingService


class InMemoryPolicyDeployments:
    """Implements ``PolicyDeploymentRepository`` in a dictionary and a
    list, which a test reads: ``kept`` by tenant, repository and commit,
    and ``puts`` in the order they were put in force, every tenant's
    together. ``now`` is asked for the time each deployment is put in
    force, and ``journal`` records its facts.
    """

    def __init__(
        self,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        journal: RecordingService | None = None,
    ) -> None:
        self._now = now
        self._journal = journal
        self.kept: dict[tuple[str, str, str], PolicyDeployment] = {}
        self.puts: list[PutInForce] = []

    def _latest(self, tenant: str) -> PutInForce | None:
        theirs = [one for one in self.puts if one.tenant == tenant]
        return theirs[-1] if theirs else None

    def deploy(
        self, deployment: PolicyDeployment, facts: Facts = lambda _: ()
    ) -> bool:
        key = (deployment.tenant, deployment.repository, deployment.commit)
        earlier = self.kept.get(key)
        if (
            earlier is not None
            and earlier.content_hash != deployment.content_hash
        ):
            raise PolicyDeploymentConflictError(*key[1:])
        latest = self._latest(deployment.tenant)
        if latest and (latest.repository, latest.commit) == key[1:]:
            self.kept[key] = deployment
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
        self.kept[key] = deployment
        self.puts.append(
            PutInForce(
                repository=deployment.repository,
                commit=deployment.commit,
                content_hash=deployment.content_hash,
                at=self._now(),
                tenant=deployment.tenant,
            )
        )
        return True

    def in_force(
        self, tenant: str = DEFAULT_TENANT
    ) -> PolicyDeployment | None:
        latest = self._latest(tenant)
        if latest is None:
            return None
        return self.kept[(tenant, latest.repository, latest.commit)]

    def last_put_in_force(
        self, tenant: str = DEFAULT_TENANT
    ) -> PutInForce | None:
        return self._latest(tenant)

    def tenants(self) -> tuple[str, ...]:
        return tuple(sorted({one.tenant for one in self.puts}))
