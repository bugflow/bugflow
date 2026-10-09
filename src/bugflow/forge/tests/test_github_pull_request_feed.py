"""Tests of listing changed pull requests and comments from GitHub, as the
poller does.
"""

from datetime import UTC, datetime
from typing import Any

import httpx2

from bugflow.forge.infrastructure.github import PER_PAGE, GitHubForge
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


def payload(number: int, updated_at: str, **changes: Any) -> dict[str, Any]:
    return {
        "number": number,
        "state": "open",
        "title": f"Pull request {number}",
        "body": None,
        "head": {"sha": f"{number:040d}"},
        "updated_at": updated_at,
        "closed_at": None,
    } | changes


def forge(
    pages: list[list[dict[str, Any]]], seen: list[httpx2.Request]
) -> GitHubForge:
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        page = int(request.url.params.get("page", "1"))
        return httpx2.Response(
            200, json=pages[page - 1] if page <= len(pages) else []
        )

    return GitHubForge("t", transport=httpx2.MockTransport(handler))


def test_without_a_since_every_open_pull_request_is_listed() -> None:
    seen: list[httpx2.Request] = []
    pulls = forge(
        [[payload(6, "2026-09-01T00:00:00Z")]], seen
    ).updated_pull_requests("o", "r", None)
    assert [p.ref.number for p in pulls] == [6]
    params = seen[0].url.params
    assert (params["state"], params["sort"], params["direction"]) == (
        "open",
        "updated",
        "desc",
    )
    assert seen[0].url.path == "/repos/o/r/pulls"


def test_listing_stops_at_the_first_pull_request_older_than_since() -> None:
    seen: list[httpx2.Request] = []
    pages = [
        [payload(n, "2026-09-11T10:00:00Z") for n in range(PER_PAGE)],
        [
            payload(200, "2026-09-11T09:30:00Z"),
            payload(201, "2026-09-11T08:00:00Z"),
            payload(202, "2026-09-11T07:00:00Z"),
        ],
    ]
    since = datetime(2026, 9, 11, 9, 0, tzinfo=UTC)
    pulls = forge(pages, seen).updated_pull_requests("o", "r", since)
    assert len(pulls) == PER_PAGE + 1
    assert pulls[-1].ref.number == 200
    assert [r.url.params["page"] for r in seen] == ["1", "2"]
    assert seen[0].url.params["state"] == "all"


def test_a_listed_pull_request_carries_what_the_delivery_id_needs() -> None:
    seen: list[httpx2.Request] = []
    closed = payload(
        9,
        "2026-09-11T10:00:00Z",
        state="closed",
        body="Why.",
        closed_at="2026-09-11T09:59:00Z",
    )
    (pull,) = forge([[closed]], seen).updated_pull_requests("o", "r", None)
    assert pull.ref == PullRequestRef(owner="o", repo="r", number=9)
    assert not pull.open
    assert pull.head_sha == "9".zfill(40)
    assert (pull.title, pull.body) == ("Pull request 9", "Why.")
    assert pull.closed_at == datetime(2026, 9, 11, 9, 59, tzinfo=UTC)


def comment_payload(
    comment_id: int, number: int, on_pull: bool
) -> dict[str, Any]:
    kind = "pull" if on_pull else "issues"
    return {
        "id": comment_id,
        "html_url": f"https://github.com/o/r/{kind}/{number}#issuecomment-1",
        "issue_url": f"https://api.github.com/repos/o/r/issues/{number}",
        "user": {"login": "reviewer"},
        "body": "/dismiss ED-01 a reason",
        "updated_at": "2026-09-12T10:00:00Z",
    }


def test_comments_on_pull_requests_are_listed_since_the_time() -> None:
    seen: list[httpx2.Request] = []
    since = datetime(2026, 9, 12, 9, 0, tzinfo=UTC)
    pages = [[comment_payload(1, 7, True), comment_payload(2, 8, False)]]
    (only,) = forge(pages, seen).updated_comments("o", "r", since)
    assert only.ref == PullRequestRef(owner="o", repo="r", number=7)
    assert (only.comment_id, only.author) == (1, "reviewer")
    assert seen[0].url.path == "/repos/o/r/issues/comments"
    params = seen[0].url.params
    assert (params["since"], params["sort"], params["direction"]) == (
        "2026-09-12T09:00:00Z",
        "updated",
        "asc",
    )


def closed_payload(number: int) -> dict[str, Any]:
    return {
        "number": number,
        "state": "closed",
        "head": {"sha": "a" * 40},
        "title": "Add the poller",
        "body": None,
        "updated_at": "2026-09-11T12:00:00Z",
        "closed_at": "2026-09-11T12:00:00Z",
    }


def test_closed_pull_requests_are_listed_a_page_at_a_time_oldest_first() -> (
    None
):
    asked: list[dict[str, str]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        asked.append(dict(request.url.params))
        page = int(request.url.params["page"])
        count = PER_PAGE if page == 1 else 3
        return httpx2.Response(
            200, json=[closed_payload(n) for n in range(count)]
        )

    forge = GitHubForge("t", transport=httpx2.MockTransport(handler))
    first = forge.closed_pull_requests("o", "r", 1)
    second = forge.closed_pull_requests("o", "r", 2)
    assert (len(first.pulls), first.last) == (PER_PAGE, False)
    assert (len(second.pulls), second.last) == (3, True)
    assert {
        k: asked[1][k] for k in ("state", "sort", "direction", "page")
    } == {
        "state": "closed",
        "sort": "created",
        "direction": "asc",
        "page": "2",
    }
