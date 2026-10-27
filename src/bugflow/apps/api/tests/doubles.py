"""The API built over in-memory stores, for tests of its routes."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from bugflow.apps.api.api import PolicyDeploying, create_api
from bugflow.apps.api.role_policy_deployment_access import (
    RolePolicyDeploymentAccess,
)
from bugflow.apps.api.settings import PageSignIn, SettingsAdministration
from bugflow.apps.shared.deploying import Deploying, deployment_check
from bugflow.apps.shared.policies import reviewers_in_force
from bugflow.forge.infrastructure.sqlalchemy_known_repositories import (
    InMemoryKnownRepositories,
)
from bugflow.method.infrastructure.in_memory_policy_deployments import (
    InMemoryPolicyDeployments,
)
from bugflow.method.usecases.deploy_policies import DeployPoliciesUseCase
from bugflow.review.infrastructure.in_memory_gnome_settings import (
    InMemoryGnomeSettings,
)
from bugflow.review.infrastructure.in_memory_layer_boundaries import (
    InMemoryLayerBoundaries,
)
from bugflow.review.usecases.set_gnome import SetGnomeUseCase
from bugflow.shared.domain.errors import TokenRefusedError
from bugflow.shared.domain.values.caller import Caller
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal

#: The role the server is told may deploy.
DEPLOYER = "a-deployer"
#: The role the server is told may read and change the settings.
ADMINISTRATOR = "an-administrator"
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
        self.settings = InMemoryGnomeSettings()
        self.deploying = Deploying(
            deploy=DeployPoliciesUseCase(
                self.deployments,
                deployment_check(CHECKS, self.settings),
                self.journal,
                Clock(),
            ),
            deployments=self.deployments,
        )
        self.repositories = InMemoryKnownRepositories()
        self.boundaries = InMemoryLayerBoundaries()
        self.client = TestClient(
            create_api(
                Tokens(),
                PolicyDeploying(
                    access=RolePolicyDeploymentAccess(DEPLOYER),
                    deploying=self.deploying,
                ),
                administration=SettingsAdministration(
                    role=ADMINISTRATOR,
                    settings=self.settings,
                    set_gnome=lambda: SetGnomeUseCase(
                        self.settings, self.journal, Clock(), "run-1"
                    ),
                    repositories=self.repositories.everything,
                    reviewers=lambda: reviewers_in_force(
                        self.deployments, CHECKS
                    ),
                    boundaries=self.boundaries,
                    sign_in=PageSignIn(
                        issuer="https://issuer.example",
                        client_id="settings-page",
                    ),
                ),
            )
        )


def bearer(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {role}"}
