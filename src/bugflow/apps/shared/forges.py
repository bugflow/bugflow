"""The forge settings the programs read: a token for github.com, and
the address and token of a Forgejo.

Every program that talks to a forge reads them here, so a token is named
by one variable everywhere.
"""

from collections.abc import Mapping


def forge_token(environ: Mapping[str, str]) -> str | None:
    """The token for github.com: ``FORGE_TOKEN``, or ``GITHUB_TOKEN``
    where only that is set. None where neither is."""
    return environ.get("FORGE_TOKEN") or environ.get("GITHUB_TOKEN") or None


def forgejo_settings(environ: Mapping[str, str]) -> tuple[str, str] | None:
    """The Forgejo's URL and token, ``FORGEJO_URL`` and ``FORGEJO_TOKEN``,
    when both are set. None where either is not."""
    url = environ.get("FORGEJO_URL")
    token = environ.get("FORGEJO_TOKEN")
    return (url, token) if url and token else None
