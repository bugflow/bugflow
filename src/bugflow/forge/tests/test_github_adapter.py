"""Tests that the GitHub adapter turns API responses into a snapshot, and
failures into the right errors.

The responses in ``recorded/github_pull_request`` are invented. They have
the shape of GitHub's, with only the fields the adapter reads.
"""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest

from bugflow.forge.domain.errors import (
    ForgeError,
    ForgeRejectedError,
    ForgeUnavailableError,
)
from bugflow.forge.infrastructure.github import (
    PER_PAGE,
    GitHubForge,
    snapshot_from_payloads,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

FIXTURES = Path(__file__).parent / "recorded" / "github_pull_request"
REF = PullRequestRef(owner="someone", repo="one", number=6)


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def test_payloads_become_a_snapshot() -> None:
    snapshot = snapshot_from_payloads(
        REF, load("pull.json"), load("commits.json"), load("files.json")
    )
    assert snapshot.title == "Say what a retry waits for"
    assert (snapshot.head_branch, snapshot.base_branch) == (
        "explain-the-retry",
        "master",
    )
    (commit,) = snapshot.commits
    assert commit.sha.startswith("4f9c2a7")
    assert commit.summary == "Say what a retry waits for"
    (changed,) = snapshot.files
    assert (changed.path, changed.additions, changed.deletions) == (
        "README.md",
        13,
        5,
    )
    assert changed.patch is not None
    assert snapshot.changed_lines == 18


def test_a_missing_body_becomes_an_empty_description() -> None:
    pull = load("pull.json") | {"body": None}
    snapshot = snapshot_from_payloads(REF, pull, [], [])
    assert snapshot.body == ""


def test_fetch_authenticates_and_follows_pages() -> None:
    requests: list[httpx2.Request] = []
    many_files = [
        {"filename": f"f{n}.py", "additions": 1, "deletions": 0}
        for n in range(PER_PAGE + 1)
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        path = request.url.path
        if path.endswith("/pulls/6"):
            return httpx2.Response(200, json=load("pull.json"))
        if path.endswith("/commits"):
            return httpx2.Response(200, json=load("commits.json"))
        if "/commits/" in path:
            # The endpoint for a single commit. It is called once for each
            # commit, and is where GitHub lists the paths a commit changed.
            return httpx2.Response(
                200, json={"files": [{"filename": "port.py"}]}
            )
        if path.endswith("/files"):
            page = int(request.url.params["page"])
            start = (page - 1) * PER_PAGE
            return httpx2.Response(
                200, json=many_files[start : start + PER_PAGE]
            )
        return httpx2.Response(404)

    forge = GitHubForge("token-value", transport=httpx2.MockTransport(handler))
    snapshot = forge.fetch_snapshot(REF)

    assert len(snapshot.files) == PER_PAGE + 1
    assert all(
        r.headers["Authorization"] == "Bearer token-value" for r in requests
    )
    file_pages = [r for r in requests if r.url.path.endswith("/files")]
    assert len(file_pages) == 2


def test_an_http_error_becomes_a_forge_error() -> None:
    forge = GitHubForge(
        "t", transport=httpx2.MockTransport(lambda r: httpx2.Response(404))
    )
    with pytest.raises(ForgeError, match="GitHub returned 404"):
        forge.fetch_snapshot(REF)


def failing_forge(response: httpx2.Response) -> GitHubForge:
    return GitHubForge(
        "t", transport=httpx2.MockTransport(lambda request: response)
    )


@pytest.mark.parametrize(
    ("status", "headers", "kind"),
    [
        (404, {}, ForgeRejectedError),
        (401, {}, ForgeRejectedError),
        (403, {}, ForgeRejectedError),
        (422, {}, ForgeRejectedError),
        (403, {"x-ratelimit-remaining": "0"}, ForgeUnavailableError),
        (403, {"retry-after": "30"}, ForgeUnavailableError),
        (429, {}, ForgeUnavailableError),
        (502, {}, ForgeUnavailableError),
        (503, {}, ForgeUnavailableError),
    ],
)
def test_failures_are_classified_as_transient_or_permanent(
    status: int, headers: dict[str, str], kind: type[ForgeError]
) -> None:
    forge = failing_forge(httpx2.Response(status, headers=headers))
    with pytest.raises(kind):
        forge.fetch_snapshot(REF)


def test_a_rate_limit_carries_the_wait_github_asked_for() -> None:
    forge = failing_forge(httpx2.Response(403, headers={"retry-after": "30"}))
    with pytest.raises(ForgeUnavailableError) as raised:
        forge.fetch_snapshot(REF)
    assert raised.value.retry_after == timedelta(seconds=30)


def test_a_secondary_limit_without_a_wait_waits_a_minute() -> None:
    forge = failing_forge(httpx2.Response(429))
    with pytest.raises(ForgeUnavailableError) as raised:
        forge.fetch_snapshot(REF)
    assert raised.value.retry_after == timedelta(minutes=1)


def test_a_network_failure_is_transient() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    forge = GitHubForge("t", transport=httpx2.MockTransport(refuse))
    with pytest.raises(ForgeUnavailableError, match="could not reach"):
        forge.fetch_snapshot(REF)
