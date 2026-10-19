"""The forge settings the programs read: the tokens for github.com, and
the address and token of a Forgejo.

Every program that talks to a forge reads them here, so a token is named
by one variable everywhere.
"""

from collections.abc import Mapping

from bugflow.forge.infrastructure.github import GitHubTokens


def forge_tokens(environ: Mapping[str, str]) -> GitHubTokens | None:
    """The tokens for github.com. ``FORGE_TOKEN`` is the token for any
    owner, or ``GITHUB_TOKEN`` where only that is set.
    ``FORGE_TOKENS_BY_OWNER`` holds a token for each owner that has its
    own, as ``owner=token`` pairs separated by commas. None where none
    is set. A pair with no ``=`` or an empty side is a ``ValueError``."""
    any_owner = (
        environ.get("FORGE_TOKEN") or environ.get("GITHUB_TOKEN") or None
    )
    by_owner: dict[str, str] = {}
    for pair in environ.get("FORGE_TOKENS_BY_OWNER", "").split(","):
        if not pair.strip():
            continue
        owner, equals, token = pair.strip().partition("=")
        if not equals or not owner.strip() or not token.strip():
            raise ValueError(
                "FORGE_TOKENS_BY_OWNER holds owner=token pairs separated by "
                f"commas; {pair.strip()!r} is not one"
            )
        by_owner[owner.strip().lower()] = token.strip()
    if not any_owner and not by_owner:
        return None
    return GitHubTokens(any_owner=any_owner, by_owner=by_owner)


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
