"""Request an API token for the caller through Zitadel token exchange."""

from contextlib import suppress
from ipaddress import ip_address
from urllib.parse import urlsplit

import httpx2

from bugflow.shared.domain.errors import TokenRefusedError

GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN = "urn:ietf:params:oauth:token-type:access_token"
JWT = "urn:ietf:params:oauth:token-type:jwt"
ROLES_SCOPE = "urn:zitadel:iam:org:projects:roles"
_REFUSED = "the caller's token could not be exchanged"


def _issuer_url(issuer: str) -> str:
    try:
        parsed = urlsplit(issuer)
        host = parsed.hostname
        _ = parsed.port  # Parsing the port rejects malformed authorities.
        loopback = host == "localhost"
        if host and not loopback:
            with suppress(ValueError):
                loopback = ip_address(host).is_loopback
        allowed = parsed.scheme == "https" or (
            parsed.scheme == "http" and loopback
        )
        if (
            not host
            or not allowed
            or parsed.username is not None
            or parsed.password is not None
            or "?" in issuer
            or "#" in issuer
            or "\\" in issuer
            or any(
                character.isspace() or ord(character) < 32
                for character in issuer
            )
        ):
            raise ValueError
    except ValueError:
        raise ValueError(
            "token issuer must use HTTPS or loopback HTTP "
            "without credentials, query or fragment"
        ) from None
    return f"{issuer.rstrip('/')}/oauth/v2/token"


class ZitadelTokenExchange:
    def __init__(
        self,
        issuer: str,
        client_id: str,
        client_secret: str,
        audience: str,
        client: httpx2.Client | None = None,
    ) -> None:
        self._url = _issuer_url(issuer)
        if any(
            not value.strip() for value in (client_id, client_secret, audience)
        ):
            raise ValueError(
                "exchange client, secret and API audience are required"
            )
        self._auth = httpx2.BasicAuth(client_id, client_secret)
        self._audience = audience
        self._owns_client = client is None
        self._client = (
            client if client is not None else httpx2.Client(timeout=15.0)
        )

    def exchange(self, token: str) -> str:
        if not token or any(character.isspace() for character in token):
            raise TokenRefusedError(_REFUSED)
        try:
            response = self._client.post(
                self._url,
                auth=self._auth,
                follow_redirects=False,
                data={
                    "grant_type": GRANT,
                    "subject_token": token,
                    "subject_token_type": ACCESS_TOKEN,
                    "requested_token_type": JWT,
                    "audience": self._audience,
                    "scope": " ".join(
                        [
                            "openid",
                            ROLES_SCOPE,
                            f"urn:zitadel:iam:org:project:id:{self._audience}:aud",
                        ]
                    ),
                },
            )
            if response.status_code != 200:
                raise TokenRefusedError(_REFUSED)
            body = response.json()
        except (httpx2.RequestError, ValueError):
            raise TokenRefusedError(_REFUSED) from None
        exchanged = (
            body.get("access_token") if isinstance(body, dict) else None
        )
        if (
            not isinstance(exchanged, str)
            or not exchanged
            or any(character.isspace() for character in exchanged)
        ):
            raise TokenRefusedError(_REFUSED)
        return exchanged

    def close(self) -> None:
        """Close the HTTP client only when this adapter created it."""
        if self._owns_client:
            self._client.close()
