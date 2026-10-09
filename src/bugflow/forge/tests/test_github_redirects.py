"""Tests that the GitHub adapter follows the redirect GitHub sends for a
renamed repository.

GitHub sends 301 for a read and 307 for a write. The adapter follows both,
keeping the request's method and token. A repository may be renamed long
after the server was told its name.
"""

import httpx2

from bugflow.forge.infrastructure.github import GitHubForge

NEW = "https://api.github.com/repositories/123"


def forge(seen: list[tuple[str, str, str]]) -> GitHubForge:
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(
            (
                request.method,
                request.url.path,
                request.headers.get("Authorization", ""),
            )
        )
        path = request.url.path
        if path.startswith("/repos/o/old"):
            rest = path.removeprefix("/repos/o/old")
            status = 301 if request.method == "GET" else 307
            return httpx2.Response(status, headers={"Location": NEW + rest})
        if path == "/repositories/123":
            return httpx2.Response(200, json={"full_name": "o/new"})
        if path == "/repositories/123/hooks":
            return httpx2.Response(200, json=[])
        if path == "/repositories/123/hooks/5":
            return httpx2.Response(204)
        return httpx2.Response(404)

    return GitHubForge("t", transport=httpx2.MockTransport(handler))


def test_a_read_follows_the_rename() -> None:
    seen: list[tuple[str, str, str]] = []
    assert forge(seen).list_hooks("o", "old") == []
    assert seen[-1] == ("GET", "/repositories/123/hooks", "Bearer t")


def test_the_current_name_is_the_name_after_the_rename() -> None:
    assert forge([]).current_name("o", "old") == "o/new"


def test_a_write_follows_the_rename_with_its_method() -> None:
    seen: list[tuple[str, str, str]] = []
    forge(seen).delete_hook("o", "old", 5)
    assert seen[-1] == ("DELETE", "/repositories/123/hooks/5", "Bearer t")


def test_a_repository_that_is_gone_has_no_current_name() -> None:
    assert forge([]).current_name("o", "gone") is None
