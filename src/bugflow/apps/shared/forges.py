"""The forge settings the programs read: the tokens for github.com, the
GitHub App signed in as, and the address and token of a Forgejo.

Every program that talks to a forge reads them here, so a token is named
by one variable everywhere.
"""

from collections.abc import Mapping
from pathlib import Path

from bugflow.forge.infrastructure.github import GitHubTokens
from bugflow.forge.infrastructure.github_app import (
    GitHubApp,
    InstallationTokens,
)

#: The settings that name GitHub tokens, for a message that says none is
#: set.
GITHUB_SETTINGS = "FORGE_TOKEN, FORGE_TOKENS_BY_OWNER or FORGE_APP_ID"


def _pairs(
    environ: Mapping[str, str], name: str, value: str
) -> dict[str, str]:
    """The ``owner=value`` pairs the setting ``name`` holds, separated by
    commas, keyed by the owner in lower case. A pair with no ``=`` or an
    empty side is a ``ValueError``."""
    pairs: dict[str, str] = {}
    for pair in environ.get(name, "").split(","):
        if not pair.strip():
            continue
        owner, equals, held = pair.strip().partition("=")
        if not equals or not owner.strip() or not held.strip():
            raise ValueError(
                f"{name} holds owner={value} pairs separated by commas; "
                f"{pair.strip()!r} is not one"
            )
        pairs[owner.strip().lower()] = held.strip()
    return pairs


def github_app(environ: Mapping[str, str]) -> GitHubApp | None:
    """The GitHub App signed in as. ``FORGE_APP_ID`` is the App's id;
    ``FORGE_APP_PRIVATE_KEY`` is its private key as PEM, with each line
    break written as ``\\n`` where the setting cannot hold one, or
    ``FORGE_APP_PRIVATE_KEY_FILE`` names a file that holds it;
    ``FORGE_APP_INSTALLATIONS`` holds the installation on each owner the
    App is installed on, as ``owner=id`` pairs separated by commas. None
    where no id is set. An id with no key, or an installation that is
    not a number, is a ``ValueError``."""
    app_id = environ.get("FORGE_APP_ID", "").strip()
    if not app_id:
        return None
    key = environ.get("FORGE_APP_PRIVATE_KEY", "").replace("\\n", "\n")
    key_file = environ.get("FORGE_APP_PRIVATE_KEY_FILE", "").strip()
    if not key.strip() and key_file:
        key = Path(key_file).read_text()
    if not key.strip():
        raise ValueError(
            "FORGE_APP_ID is set but neither FORGE_APP_PRIVATE_KEY nor "
            "FORGE_APP_PRIVATE_KEY_FILE gives the App's private key"
        )
    installations: dict[str, int] = {}
    for owner, raw in _pairs(environ, "FORGE_APP_INSTALLATIONS", "id").items():
        if not raw.isdigit():
            raise ValueError(
                f"FORGE_APP_INSTALLATIONS names installation {raw!r} for "
                f"{owner}, which is not a number"
            )
        installations[owner] = int(raw)
    return GitHubApp(
        app_id=app_id, private_key=key, installations=installations
    )


def forge_tokens(environ: Mapping[str, str]) -> GitHubTokens | None:
    """What github.com is signed in with. ``FORGE_TOKEN`` is the token
    for any owner, or ``GITHUB_TOKEN`` where only that is set.
    ``FORGE_TOKENS_BY_OWNER`` holds a token for each owner that has its
    own, as ``owner=token`` pairs separated by commas. The App
    ``github_app`` reads signs in to each owner it is installed on. None
    where none is set. A pair with no ``=`` or an empty side is a
    ``ValueError``."""
    any_owner = (
        environ.get("FORGE_TOKEN") or environ.get("GITHUB_TOKEN") or None
    )
    by_owner = _pairs(environ, "FORGE_TOKENS_BY_OWNER", "token")
    app = github_app(environ)
    if not any_owner and not by_owner and app is None:
        return None
    return GitHubTokens(
        any_owner=any_owner,
        by_owner=by_owner,
        app=InstallationTokens(app) if app else None,
    )


def forgejo_settings(environ: Mapping[str, str]) -> tuple[str, str] | None:
    """The Forgejo's URL and token, ``FORGEJO_URL`` and ``FORGEJO_TOKEN``,
    when both are set. None where either is not."""
    url = environ.get("FORGEJO_URL")
    token = environ.get("FORGEJO_TOKEN")
    return (url, token) if url and token else None


def repository_endpoints(environ: Mapping[str, str]) -> dict[str, str]:
    """The configured sources for new repository-wide runs."""
    endpoints = {}
    if forge_tokens(environ) is not None:
        endpoints["github"] = "https://github.com"
    if settings := forgejo_settings(environ):
        endpoints["forgejo"] = settings[0]
    return endpoints
