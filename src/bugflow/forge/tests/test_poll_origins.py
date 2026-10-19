"""Poll provenance follows the requested endpoint, including every page."""

from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest

from bugflow.forge.domain.errors import ForgeRejectedError
from bugflow.forge.infrastructure.forgejo import ForgejoForge
from bugflow.forge.infrastructure.github import GitHubForge

NOW = datetime(2026, 9, 11, tzinfo=UTC)
PULL = {
    "number": 1,
    "state": "open",
    "head": {"sha": "sha"},
    "title": "title",
    "updated_at": NOW.isoformat(),
}
COMMENT = {
    "id": 5,
    "body": "/dismiss ED-01 reason",
    "updated_at": NOW.isoformat(),
    "html_url": "https://untrusted.test/o/r/pull/1",
    "issue_url": "https://untrusted.test/o/r/issues/1",
    "pull_request_url": "https://untrusted.test/o/r/pulls/1",
}


def adapter(kind: str, endpoint: str, transport: httpx2.MockTransport) -> Any:
    if kind == "github":
        return GitHubForge("token", transport=transport)
    return ForgejoForge(endpoint, "token", transport=transport)


@pytest.mark.parametrize("kind", ["github", "forgejo"])
@pytest.mark.parametrize("comments", [False, True])
def test_feed_records_endpoint_origin(kind: str, comments: bool) -> None:
    def serve(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=[COMMENT if comments else PULL])

    forge = adapter(
        kind, "https://FORGE.test:8443", httpx2.MockTransport(serve)
    )
    entries = (
        forge.updated_comments("o", "r", NOW)
        if comments
        else forge.updated_pull_requests("o", "r", None)
    )
    assert len(entries) == 1
    assert entries[0].origin == (
        "github.com/o/r" if kind == "github" else "forge.test:8443/o/r"
    )


@pytest.mark.parametrize("kind", ["github", "forgejo"])
@pytest.mark.parametrize("comments", [False, True])
@pytest.mark.parametrize("page", [1, 2])
def test_feed_refuses_redirects_on_every_page(
    kind: str, comments: bool, page: int
) -> None:
    seen = []

    def serve(request: httpx2.Request) -> httpx2.Response:
        seen.append(str(request.url))
        if len(seen) == page:
            return httpx2.Response(
                302, headers={"Location": "https://other.test/redirected"}
            )
        return httpx2.Response(
            200,
            json=[COMMENT if comments else PULL] * 100,
            headers={"x-total-count": "200"},
        )

    forge = adapter(kind, "https://forge.test", httpx2.MockTransport(serve))
    with pytest.raises(ForgeRejectedError):
        if comments:
            forge.updated_comments("o", "r", NOW)
        else:
            forge.updated_pull_requests("o", "r", None)
    assert len(seen) == page
    assert all("other.test" not in url for url in seen)


@pytest.mark.parametrize("comments", [False, True])
def test_http_feed_stays_unresolved(comments: bool) -> None:
    forge = adapter(
        "forgejo",
        "http://forge.test",
        httpx2.MockTransport(
            lambda request: httpx2.Response(
                200, json=[COMMENT if comments else PULL]
            )
        ),
    )
    entries = (
        forge.updated_comments("o", "r", NOW)
        if comments
        else forge.updated_pull_requests("o", "r", None)
    )
    assert entries[0].origin is None


def test_prefixed_https_endpoint_is_refused_before_reading() -> None:
    seen = []

    def serve(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=[])

    forge = adapter(
        "forgejo", "https://forge.test/prefix", httpx2.MockTransport(serve)
    )
    with pytest.raises(ForgeRejectedError):
        forge.updated_pull_requests("o", "r", None)
    assert not seen
