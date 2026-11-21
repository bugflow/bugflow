"""Telling where a repository went when a forge redirects a request
for it.

GitHub and Forgejo both answer a request for a renamed or transferred
repository with a redirect. A request that refuses redirects is
refused here with ``ForgeRepositoryMovedError``, naming the repository
it asked for and, where the forge says, the name it has now. The new
name is asked for without following a redirect to another host, so the
token is never sent off the forge.
"""

from typing import Any

import httpx2

from bugflow.forge.domain.errors import ForgeRepositoryMovedError


def repository_of(path: str) -> tuple[str, str] | None:
    """The owner and name of the repository an API path is under, or
    None for a path under none."""
    parts = path.split("/")
    if len(parts) > 3 and parts[1] == "repos" and parts[2] and parts[3]:
        return parts[2], parts[3]
    return None


def current_name(
    client: httpx2.Client, path: str, headers: dict[str, str]
) -> str | None:
    """The ``full_name`` the forge gives the repository at ``path``,
    following one redirect on the same host, or None where it gives
    none."""
    try:
        response = client.get(path, headers=headers, follow_redirects=False)
        if response.is_redirect:
            target = response.url.join(response.headers.get("location", ""))
            if target.host != response.url.host:
                return None
            response = client.get(
                str(target), headers=headers, follow_redirects=False
            )
        if response.status_code != 200:
            return None
        body: Any = response.json()
    except (httpx2.HTTPError, ValueError):
        return None
    name = body.get("full_name") if isinstance(body, dict) else None
    return str(name) if name else None


def moved(
    forge: str,
    client: httpx2.Client,
    owner: str,
    repo: str,
    headers: dict[str, str],
) -> ForgeRepositoryMovedError:
    """The error for a redirected request for ``owner/repo``, naming
    where the repository is now if the forge says."""
    asked = f"{owner}/{repo}"
    now = current_name(client, f"/repos/{owner}/{repo}", headers)
    if now is None or now == asked:
        return ForgeRepositoryMovedError(
            f"{forge} redirected the request for {asked}, and did not say "
            "where it is now; it was renamed or moved, so watch it by its "
            "new name",
            asked,
            None,
        )
    return ForgeRepositoryMovedError(
        f"{forge} says {asked} is now {now}; watch it by that name",
        asked,
        now,
    )
