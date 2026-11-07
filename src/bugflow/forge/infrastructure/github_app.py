"""Signing in to GitHub as a GitHub App.

A GitHub App has no token of its own. It holds a private key, signs a
short-lived JWT with it that names the App, and exchanges that at GitHub
for an installation access token: a token for one installation of the
App, on one organisation or user, which lasts an hour. GitHub attributes
what the token does to the App's bot, ``name[bot]``, not to a person.

``InstallationTokens`` does the exchange for each owner the App is
installed on, and keeps each token until it is about to expire. Every
request to GitHub asks ``GitHubTokens.for_owner`` for a token, and that
asks here when the owner has no token of its own.
"""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock

import httpx2
import jwt

from bugflow.forge.domain.errors import (
    ForgeRejectedError,
    ForgeUnavailableError,
)

API_URL = "https://api.github.com"

#: How long the App's JWT lives, in seconds. GitHub accepts at most ten
#: minutes; nine leaves room for a clock a minute ahead of GitHub's.
JWT_LIFETIME_SECONDS = 9 * 60

#: Seconds the JWT is dated before now, so that a clock a little ahead
#: of GitHub's does not make a token that is "not yet valid".
JWT_LEEWAY_SECONDS = 60

#: An installation token is minted again when fewer seconds than this
#: remain of its hour, so that a request begun with it does not find it
#: expired midway.
RENEW_BEFORE_SECONDS = 5 * 60


@dataclass(frozen=True)
class GitHubApp:
    """A GitHub App's credentials: its id, its private key as PEM, and
    the installation to sign in to for each owner it is installed on.
    ``installations`` is keyed by the owner's name in lower case, since
    GitHub reads an owner's name without regard to case."""

    app_id: str
    private_key: str
    installations: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class _Minted:
    token: str
    expires_at: float


class InstallationTokens:
    """Installation access tokens for a GitHub App, one for each owner
    it is installed on, each minted when first asked for and again when
    close to expiry.

    ``transport`` replaces the network, for tests; ``now`` replaces the
    clock. Minting is serialised, so two threads asking for the same
    owner's token at once mint it once.
    """

    def __init__(
        self,
        app: GitHubApp,
        transport: httpx2.BaseTransport | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._app = app
        self._now = now
        self._held: dict[str, _Minted] = {}
        self._lock = Lock()
        self._client = httpx2.Client(
            base_url=API_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
            transport=transport,
        )

    @property
    def owners(self) -> frozenset[str]:
        """The owners the App is installed on, in lower case."""
        return frozenset(self._app.installations)

    def holds(self, owner: str) -> bool:
        """Whether the App is installed on ``owner``."""
        return owner.lower() in self._app.installations

    def for_owner(self, owner: str) -> str:
        """The installation token for ``owner``, minted if none is held
        or the one held is about to expire. Raises ``ForgeRejectedError``
        where the App is not installed on ``owner``, before anything is
        sent."""
        key = owner.lower()
        installation = self._app.installations.get(key)
        if installation is None:
            raise ForgeRejectedError(
                f"the GitHub App is not installed on {owner}: name its "
                f"installation in FORGE_APP_INSTALLATIONS as "
                f"{owner}=INSTALLATION_ID"
            )
        with self._lock:
            held = self._held.get(key)
            if held is None or held.expires_at - self._now() < (
                RENEW_BEFORE_SECONDS
            ):
                held = self._mint(installation)
                self._held[key] = held
            return held.token

    def _jwt(self) -> str:
        now = int(self._now())
        return jwt.encode(
            {
                "iat": now - JWT_LEEWAY_SECONDS,
                "exp": now + JWT_LIFETIME_SECONDS,
                "iss": self._app.app_id,
            },
            self._app.private_key,
            algorithm="RS256",
        )

    def _mint(self, installation: int) -> _Minted:
        path = f"/app/installations/{installation}/access_tokens"
        try:
            response = self._client.post(
                path, headers={"Authorization": f"Bearer {self._jwt()}"}
            )
            response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            raise ForgeRejectedError(
                f"GitHub refused to mint a token for installation "
                f"{installation}: {exc.response.status_code} "
                f"{exc.response.text[:200]}"
            ) from exc
        except httpx2.RequestError as exc:
            raise ForgeUnavailableError(
                f"could not reach GitHub to mint a token: {exc}"
            ) from exc
        minted = response.json()
        expires_at = datetime.fromisoformat(
            str(minted["expires_at"]).replace("Z", "+00:00")
        )
        return _Minted(
            token=str(minted["token"]),
            expires_at=expires_at.astimezone(UTC).timestamp(),
        )
