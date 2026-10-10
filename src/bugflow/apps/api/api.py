"""The API: the two routes a policy repository's pipeline calls.

``POST /api/policy-deployments`` stores the files sent as a deployment
and puts it in force, or with ``check_only`` parses them and stores
nothing. ``GET /api/policy-deployments/in-force`` names the deployment
in force.

Every call but the healthcheck, answered at ``/`` and at
``/api/healthcheck``, carries a bearer token, checked here before
anything else is read, and then the caller's right to deploy is asked
of the access interface. A refused token answers 401 and a caller who
may not deploy 403.

Run by uvicorn with ``--factory``, as ``api_from_environment``.
"""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException

from bugflow.apps.api.role_policy_deployment_access import (
    RolePolicyDeploymentAccess,
)
from bugflow.apps.shared.deploying import (
    Deploying,
    checks_from,
    deploying_over,
)
from bugflow.apps.shared.journals import build_sha
from bugflow.method.domain.errors import (
    PolicyDeploymentConflictError,
    PolicyDeploymentError,
)
from bugflow.method.domain.services.policy_deployment_access import (
    PolicyDeploymentAccessService,
)
from bugflow.method.dtos.deploy_policies import (
    DeployPoliciesBody,
    DeployPoliciesRequest,
    DeployPoliciesResponse,
    InForce,
)
from bugflow.shared.domain.errors import TokenRefusedError
from bugflow.shared.domain.services.bearer_token import BearerTokenService
from bugflow.shared.domain.values.caller import Caller
from bugflow.shared.infrastructure.jwt_bearer_token import (
    JwtBearerToken,
    published_keys,
)


@dataclass(frozen=True)
class PolicyDeploying:
    """What the policy deployment routes are served with: who may
    deploy, and what deploys."""

    access: PolicyDeploymentAccessService
    deploying: Deploying


def create_api(
    tokens: BearerTokenService, deploying: PolicyDeploying
) -> FastAPI:
    """Build the API over the token check and what deploys."""
    app = FastAPI(title="bugflow API")

    def caller(
        authorization: Annotated[str, Header()] = "",
    ) -> Caller:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise _unauthorised()
        try:
            return tokens.verify(token.strip())
        except TokenRefusedError as exc:
            raise _unauthorised() from exc

    @app.get("/")
    @app.get("/api/healthcheck")
    def healthcheck() -> dict[str, bool]:
        """Up or not; it reads nothing and needs no token."""
        return {"ok": True}

    policy_deployment_routes(app, caller, deploying)
    return app


def policy_deployment_routes(
    app: FastAPI,
    caller: Callable[..., Caller],
    deploying: PolicyDeploying,
) -> None:
    """Add the two routes a policy repository's pipeline calls to
    ``app``. ``caller`` is the dependency that checks the bearer token.

    Another server mounts the same routes on its own API by calling
    this with its own token check.
    """

    def deployer(who: Annotated[Caller, Depends(caller)]) -> Caller:
        if not deploying.access.may_deploy(who):
            raise HTTPException(403, "this caller may not deploy policies")
        return who

    @app.post("/api/policy-deployments")
    def deploy_policies(
        who: Annotated[Caller, Depends(deployer)],
        body: DeployPoliciesBody,
    ) -> DeployPoliciesResponse:
        """Store the files as a policy deployment and put it in force,
        or with check_only parse them and store nothing.

        Sending the deployment already in force changes nothing and
        answers already_in_force, so a pipeline may repeat the call.
        Files that are not a deployment or do not parse answer 422 with
        every problem found. A commit already held with other content
        answers 409. In both cases the deployment in force is unchanged.
        """
        try:
            return deploying.deploying.deploy.execute(
                DeployPoliciesRequest(
                    **body.model_dump(),
                    sent_by=f"{who.subject} through {who.client}",
                )
            )
        except PolicyDeploymentError as exc:
            raise HTTPException(422, str(exc)) from exc
        except PolicyDeploymentConflictError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/policy-deployments/in-force")
    def policy_deployment_in_force(
        who: Annotated[Caller, Depends(deployer)],
    ) -> InForce:
        """The deployment in force, by its repository, commit and
        content hash. 404 on a server that was never sent one."""
        latest = deploying.deploying.deployments.last_put_in_force()
        if latest is None:
            raise HTTPException(404, "no policy deployment is in force")
        return InForce(
            repository=latest.repository,
            commit=latest.commit,
            content_hash=latest.content_hash,
        )


def _unauthorised() -> HTTPException:
    return HTTPException(
        401,
        "a bearer token is required",
        headers={"WWW-Authenticate": "Bearer"},
    )


#: The settings the API does not start without.
REQUIRED = (
    "API_ISSUER",
    "API_AUDIENCE",
    "API_CLIENTS",
    "API_ROLES_CLAIM",
    "POLICY_DEPLOYER_ROLE",
    "DATABASE_URL",
)


def api_from_environment(
    environ: Mapping[str, str] | None = None,
    key: Callable[[str], object] | None = None,
) -> FastAPI:
    """Build the API from environment variables. This is what uvicorn
    calls, with ``--factory``.

    Required, and the API refuses to start without them:

    - ``API_ISSUER``: the identity provider's address.
    - ``API_AUDIENCE``: the audience a token must be addressed to.
    - ``API_CLIENTS``: client ids a token may come from, comma-separated.
    - ``API_ROLES_CLAIM``: the name of the token claim that lists a
      caller's roles.
    - ``POLICY_DEPLOYER_ROLE``: the role that may deploy policies.
    - ``DATABASE_URL``: the Postgres database deployments are kept in,
      which holds the journal and the declarations too.

    Optional:

    - ``BUILD_SHA``: the full git sha of the build, recorded with every
      journal entry.
    - ``POLICY_CHECKS``: the checks this server performs, comma-separated.
      Unset, they are the ones the package has; empty, a manifest naming
      a check is refused.

    The database is not brought up to date here; ``bugflow migrate``
    does that.

    ``key`` replaces the lookup of the provider's signing keys, for tests.
    """
    environ = os.environ if environ is None else environ
    missing = [name for name in REQUIRED if not environ.get(name)]
    if missing:
        raise ValueError(
            f"{', '.join(missing)} not set; the API does not start "
            "without them"
        )
    issuer = environ["API_ISSUER"]
    clients = [
        client.strip()
        for client in environ["API_CLIENTS"].split(",")
        if client.strip()
    ]
    return create_api(
        JwtBearerToken(
            issuer,
            environ["API_AUDIENCE"],
            clients,
            key or published_keys(issuer),
            environ["API_ROLES_CLAIM"],
        ),
        PolicyDeploying(
            access=RolePolicyDeploymentAccess(environ["POLICY_DEPLOYER_ROLE"]),
            deploying=deploying_over(
                environ["DATABASE_URL"],
                build_sha(environ),
                checks_from(environ),
            ),
        ),
    )
