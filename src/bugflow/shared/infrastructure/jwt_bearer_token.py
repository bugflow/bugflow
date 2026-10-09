"""Checks a bearer token that is a JWT signed by an identity provider.

A token is accepted when all of these hold:

- it is signed with one of the provider's public keys;
- its issuer is the provider;
- its audience is this server;
- it has not expired;
- it was issued to one of the clients this server expects.

The check is done here, with the provider's public keys. The provider is
asked for its keys, and those are cached; it is not asked about each token.

Nothing here is specific to one provider. The address of the keys is read
from the provider's OpenID Connect discovery document. The name of the
claim that lists a person's roles is a setting, because providers use
different names.
"""

import json
import urllib.request
from collections.abc import Callable, Collection
from threading import Lock
from typing import Any

import jwt

from bugflow.shared.domain.errors import TokenRefusedError
from bugflow.shared.domain.values.caller import Caller

#: Seconds of clock difference allowed between this server and the
#: provider. Without it, a token issued a moment ago can be refused as
#: "not yet valid".
LEEWAY_SECONDS = 60

#: Seconds to wait for the provider when fetching its discovery
#: document or its keys.
WAIT_SECONDS = 10

#: A function that takes a token and returns the public key it was
#: signed with.
type SigningKey = Callable[[str], Any]


def _published(issuer: str) -> dict[str, Any]:
    """Fetch the provider's OpenID Connect discovery document: a JSON object
    at a standard path that says, among other things, where its keys are.
    """
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
    """Return a function that finds the public key a token was signed with.

    The function reads the address of the keys (``jwks_uri``) from the
    provider's discovery document, then fetches and caches the keys. It
    first contacts the provider when the first token is checked, not when
    the server starts, so the server can start while the provider is down.

    ``published`` replaces the fetch of the discovery document, for tests.
    """
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
    """Implements ``BearerTokenService`` for JWTs.

    ``issuer`` is the provider's address. ``audience`` is the audience a
    token must have. ``clients`` are the client ids a token may be issued
    to. ``key`` finds the public key for a token. ``roles_claim`` is the
    name of the claim that lists the person's roles.
    """

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
            # The provider could not be reached, or its discovery
            # document does not say where its keys are. Without keys no
            # token can be checked, so the token is refused.
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
            # A valid token issued to some other application has the
            # right issuer and audience too. The client id is what
            # shows it was not issued to an application this server
            # expects.
            raise TokenRefusedError(f"issued to {client or 'no client'}")
        roles = claims.get(self._roles_claim) or []
        if not isinstance(roles, list):
            raise TokenRefusedError(f"{self._roles_claim} is not a list")
        return Caller(
            subject=str(claims["sub"]),
            client=client,
            roles=frozenset(str(role) for role in roles),
        )
