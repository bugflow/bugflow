"""The API built over in-memory stores, for tests of its routes."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from bugflow.apps.api.api import PolicyDeploying, create_api
from bugflow.apps.api.role_policy_deployment_access import (
    RolePolicyDeploymentAccess,
)
from bugflow.apps.shared.deploying import (
    Deploying,
    DeployPoliciesAndDeclare,
    deployment_check,
)
from bugflow.method.infrastructure.in_memory_policy_deployments import (
    InMemoryPolicyDeployments,
)
from bugflow.method.usecases.deploy_policies import DeployPoliciesUseCase
from bugflow.review.infrastructure.in_memory_review_declaration import (
    InMemoryDispatchedProcesses,
    InMemoryJudgedPolicies,
)
from bugflow.shared.domain.errors import TokenRefusedError
from bugflow.shared.domain.values.caller import Caller
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal

#: The role the server is told may deploy.
DEPLOYER = "a-deployer"
#: A role the server is not told about.
READER = "a-reader"
#: The checks the server is told it has.
CHECKS = ("em-dash",)
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


class Tokens:
    """The server's token check: a token is a role name. "nobody" holds
    no role, and "refused" is not accepted."""

    def __init__(self, subject: str = "machine-user-1") -> None:
        self.subject = subject

    def verify(self, token: str) -> Caller:
        if token == "refused":
            raise TokenRefusedError("refused for the test")
        return Caller(
            subject=self.subject,
            client="policies-pipeline",
            roles=frozenset() if token == "nobody" else frozenset({token}),
        )


class Server:
    """The API over in-memory stores, each store readable by a test."""

    def __init__(self) -> None:
        self.deployments = InMemoryPolicyDeployments()
        self.journal = InMemoryJournal()
        self.judged = InMemoryJudgedPolicies()
        self.dispatched = InMemoryDispatchedProcesses()
        self.deploying = Deploying(
            deploy=DeployPoliciesAndDeclare(
                DeployPoliciesUseCase(
                    self.deployments,
                    deployment_check(CHECKS),
                    self.journal,
                    Clock(),
                ),
                self.deployments,
                self.judged,
                self.dispatched,
                CHECKS,
            ),
            deployments=self.deployments,
        )
        self.client = TestClient(
            create_api(
                Tokens(),
                PolicyDeploying(
                    access=RolePolicyDeploymentAccess(DEPLOYER),
                    deploying=self.deploying,
                ),
            )
        )


def bearer(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {role}"}
