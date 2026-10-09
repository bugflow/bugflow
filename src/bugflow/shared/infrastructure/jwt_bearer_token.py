"""Bearer tokens checked here, as an identity provider's JWTs.

A token is accepted when it is signed with one of the provider's
published keys, names the provider as its issuer, is addressed to this
server, has not expired, and was issued to a client this server
expects. The provider is asked for its keys and never about a token,
so a check costs no call to it once the keys are held.

Nothing here is one provider's. Where its keys are is read from what
it publishes about itself, and which claim carries a person's roles is
given, since providers differ.
"""

import json
import urllib.request
from collections.abc import Callable, Collection
from threading import Lock
from typing import Any

import jwt

from bugflow.shared.domain.errors import TokenRefusedError
from bugflow.shared.domain.values.caller import Caller

#: A clock a second ahead of the provider's makes a fresh token "not yet
#: valid" without it.
LEEWAY_SECONDS = 60

#: How long the provider is waited for, in seconds, when it is asked
#: what it publishes or for its keys.
WAIT_SECONDS = 10

#: The key a token was signed with, found from the token's header.
type SigningKey = Callable[[str], Any]


def _published(issuer: str) -> dict[str, Any]:
    """What the provider publishes about itself (OpenID Connect
    Discovery)."""
    url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    with urllib.request.urlopen(url, timeout=WAIT_SECONDS) as answered:
        found = json.load(answered)
    if not isinstance(found, dict):
        raise ValueError(f"{url} did not answer an object")
    return found


def published_keys(
    issuer: str,
    published: Callable[[str], dict[str, Any]] = _published,
) -> SigningKey:
    """The provider's keys, found at the ``jwks_uri`` it publishes, then
    fetched and cached. The provider is first asked when the first token
    is checked, so a server starts while its provider is away."""
    lock = Lock()
    clients: list[jwt.PyJWKClient] = []

    def key(token: str) -> Any:
        with lock:
            if not clients:
                clients.append(
                    jwt.PyJWKClient(
                        str(published(issuer)["jwks_uri"]),
                        timeout=WAIT_SECONDS,
                    )
                )
        return clients[0].get_signing_key_from_jwt(token).key

    return key


class JwtBearerToken:
    """Satisfies ``BearerTokenService`` for tokens ``issuer`` signs,
    addressed to ``audience``, from one of ``clients``, with a person's
    roles in the claim ``roles_claim``."""

    def __init__(
        self,
        issuer: str,
        audience: str,
        clients: Collection[str],
        key: SigningKey,
        roles_claim: str,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._clients = frozenset(clients)
        self._key = key
        self._roles_claim = roles_claim

    def verify(self, token: str) -> Caller:
        try:
            signed_with = self._key(token)
        except jwt.PyJWTError as exc:
            raise TokenRefusedError(str(exc)) from exc
        except (OSError, ValueError, KeyError) as exc:
            # The provider could not be asked, or what it publishes
            # names no keys: nobody can be vouched for.
            raise TokenRefusedError(
                f"the provider's keys could not be had: {exc}"
            ) from exc
        try:
            claims = jwt.decode(
                token,
                signed_with,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise TokenRefusedError(str(exc)) from exc
        client = str(claims.get("client_id") or claims.get("azp") or "")
        if client not in self._clients:
            # A token taken from elsewhere and presented here is
            # addressed to this server too; the client is what says it
            # did not come through one this server expects.
            raise TokenRefusedError(f"issued to {client or 'no client'}")
        roles = claims.get(self._roles_claim) or []
        if not isinstance(roles, list):
            raise TokenRefusedError(f"{self._roles_claim} is not a list")
        return Caller(
            subject=str(claims["sub"]),
            client=client,
            roles=frozenset(str(role) for role in roles),
        )
