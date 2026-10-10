"""Send a deployment to a server's API over HTTP.

The sender is a pipeline, a client of the identity provider with no
person behind it. It asks the provider for a token with the
client_credentials grant and posts the files to the server's
``/api/policy-deployments`` route with that token.
"""

from dataclasses import dataclass
from typing import Any, get_args

import httpx2

from bugflow.method.domain.errors import (
    PoliciesRefusedError,
    PolicyServerError,
)
from bugflow.method.domain.models.policy_deployment import PolicyDeployment
from bugflow.method.domain.values.server_answer import (
    InForce,
    Outcome,
    ServerAnswer,
)

#: The scope that asks the provider to put the client's roles in the
#: token.
ROLES_SCOPE = "urn:zitadel:iam:org:projects:roles"
#: The role a client needs on the server to deploy policies.
DEPLOYER_ROLE = "bugflow-policy-deployer"


@dataclass(frozen=True, kw_only=True)
class PipelineSignIn:
    """How a pipeline signs in to the identity provider."""

    #: The identity provider's address.
    issuer: str
    client_id: str
    client_secret: str
    #: The id of the server's project at the provider. The server
    #: expects it in the token's audience.
    audience: str


class HttpPolicyServer:
    """Implements ``PolicyServerService`` over a server's API."""

    def __init__(
        self,
        api: str,
        sign_in: PipelineSignIn,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._api = api.rstrip("/")
        self._sign_in = sign_in
        self._transport = transport

    def send(
        self, deployment: PolicyDeployment, check_only: bool
    ) -> ServerAnswer:
        with httpx2.Client(timeout=60.0, transport=self._transport) as client:
            token = self._token(client)
            try:
                answered = client.post(
                    f"{self._api}/api/policy-deployments",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "repository": deployment.repository,
                        "commit": deployment.commit,
                        "files": [
                            {"path": one.path, "text": one.text}
                            for one in deployment.files
                        ],
                        "check_only": check_only,
                    },
                )
            except httpx2.HTTPError as exc:
                raise PolicyServerError(
                    f"could not reach the server at {self._api}: {exc}"
                ) from exc
        if answered.status_code in (409, 422):
            raise PoliciesRefusedError(_detail(answered))
        if answered.status_code == 401:
            raise PolicyServerError(
                "the server did not accept the token; check that the "
                "audience is the server's project and that the server "
                "lists this client"
            )
        if answered.status_code == 403:
            raise PolicyServerError(
                "this client may not deploy policies; it needs the role "
                f"{DEPLOYER_ROLE}"
            )
        if answered.status_code != 200:
            raise PolicyServerError(
                f"the server answered {answered.status_code}: "
                f"{_detail(answered)}"
            )
        try:
            return _answer(answered.json())
        except (KeyError, TypeError, ValueError) as exc:
            raise PolicyServerError(
                f"the server's answer could not be read: {answered.text}"
            ) from exc

    def _token(self, client: httpx2.Client) -> str:
        """A bearer token for the pipeline, from the identity provider.

        Three scopes are asked for. Without the audience scope the
        server refuses the token, and without the roles scope the token
        carries no role.
        """
        issuer = self._sign_in.issuer.rstrip("/")
        try:
            discovery = client.get(
                f"{issuer}/.well-known/openid-configuration"
            )
            discovery.raise_for_status()
            answered = client.post(
                discovery.json()["token_endpoint"],
                auth=(self._sign_in.client_id, self._sign_in.client_secret),
                data={
                    "grant_type": "client_credentials",
                    "scope": " ".join(
                        (
                            "openid",
                            "urn:zitadel:iam:org:project:id:"
                            f"{self._sign_in.audience}:aud",
                            ROLES_SCOPE,
                        )
                    ),
                },
            )
        except (httpx2.HTTPError, KeyError, ValueError) as exc:
            raise PolicyServerError(
                f"could not reach the identity provider at {issuer}: {exc}"
            ) from exc
        if answered.status_code != 200:
            raise PolicyServerError(
                "the identity provider refused the client's credentials "
                f"({answered.status_code})"
            )
        try:
            token = answered.json().get("access_token")
        except ValueError:
            token = None
        if not token:
            raise PolicyServerError("the identity provider answered no token")
        return str(token)


def _answer(said: dict[str, Any]) -> ServerAnswer:
    in_force = said.get("in_force")
    outcome = said["outcome"]
    if outcome not in get_args(Outcome):
        raise ValueError(outcome)
    return ServerAnswer(
        outcome=outcome,
        content_hash=said["content_hash"],
        in_force=InForce(
            repository=in_force["repository"],
            commit=in_force["commit"],
            content_hash=in_force["content_hash"],
        )
        if in_force
        else None,
    )


def _detail(answered: httpx2.Response) -> str:
    """The server's reason, from the body's detail if it has one."""
    try:
        return str(answered.json().get("detail", answered.text))
    except (ValueError, AttributeError):
        return answered.text
