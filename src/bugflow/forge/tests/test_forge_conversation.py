"""Tests of reading a pull request's discussion after it has closed: the
reactions on a comment, and whether the pull request was merged.

GitHub sends no delivery when someone reacts to a comment, so reactions are
read from the API when the pull request closes.
"""

from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest

from bugflow.forge.domain.errors import ForgeRejectedError
from bugflow.forge.domain.values.conversation import PullRequestState, Reaction
from bugflow.forge.infrastructure.forgejo import ForgejoForge
from bugflow.forge.infrastructure.github import GitHubForge
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="o", repo="r", number=7)
ON_FORGEJO = PullRequestRef(forge="forgejo", owner="o", repo="r", number=7)
REACTIONS = [
    {
        "id": 1,
        "user": {"login": "someone"},
        "content": "+1",
        "created_at": "2026-09-22T05:00:00Z",
    },
    {"id": 2, "user": {"login": "sam"}, "content": "-1", "created_at": None},
]
PULL = {"state": "closed", "merged": True, "head": {"sha": "c" * 40}}


def answering(paths: dict[str, Any], seen: list[str]) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        return httpx2.Response(200, json=paths[request.url.path])

    return httpx2.MockTransport(handler)


def test_github_reads_the_reactions_on_one_comment() -> None:
    seen: list[str] = []
    forge = GitHubForge(
        "t",
        transport=answering(
            {"/repos/o/r/issues/comments/42/reactions": REACTIONS}, seen
        ),
    )

    reactions = forge.reactions(REF, 42)

    assert seen == ["/repos/o/r/issues/comments/42/reactions"]
    assert reactions == (
        Reaction(
            content="+1",
            login="someone",
            reacted_at=datetime(2026, 9, 22, 5, tzinfo=UTC),
        ),
        Reaction(content="-1", login="sam", reacted_at=None),
    )


def test_github_says_whether_a_pull_request_merged_and_at_which_head() -> None:
    seen: list[str] = []
    forge = GitHubForge(
        "t", transport=answering({"/repos/o/r/pulls/7": PULL}, seen)
    )

    assert forge.state(REF) == PullRequestState(
        merged=True, head_sha="c" * 40, origin="github.com/o/r"
    )


def test_forgejo_reads_the_reactions_on_one_comment() -> None:
    seen: list[str] = []
    forge = ForgejoForge(
        "https://forgejo.example",
        "t",
        transport=answering(
            {"/api/v1/repos/o/r/issues/comments/42/reactions": REACTIONS},
            seen,
        ),
    )

    assert [r.content for r in forge.reactions(ON_FORGEJO, 42)] == ["+1", "-1"]


def test_forgejo_says_whether_a_pull_request_merged() -> None:
    seen: list[str] = []
    forge = ForgejoForge(
        "https://forgejo.example",
        "t",
        transport=answering({"/api/v1/repos/o/r/pulls/7": PULL}, seen),
    )

    assert forge.state(ON_FORGEJO).merged


@pytest.mark.parametrize("kind", ["github", "forgejo"])
@pytest.mark.parametrize("operation", ["state", "reactions"])
def test_close_reads_refuse_redirects(kind: str, operation: str) -> None:
    seen: list[str] = []

    def redirect(request: httpx2.Request) -> httpx2.Response:
        seen.append(str(request.url))
        return httpx2.Response(
            302, headers={"Location": "https://other.test/redirected"}
        )

    transport = httpx2.MockTransport(redirect)
    forge = (
        GitHubForge("token", transport=transport)
        if kind == "github"
        else ForgejoForge("https://forge.test", "token", transport=transport)
    )
    with pytest.raises(ForgeRejectedError):
        if operation == "state":
            forge.state(REF)
        else:
            forge.reactions(REF, 42)
    assert len(seen) == 1
    assert "other.test" not in seen[0]


@pytest.mark.parametrize(
    "endpoint, origin",
    [
        ("https://FORGE.test:8443", "forge.test:8443/o/r"),
        ("http://forge.test", None),
    ],
)
def test_closing_source_comes_from_forgejo_endpoint(
    endpoint: str, origin: str | None
) -> None:
    forge = ForgejoForge(
        endpoint,
        "token",
        transport=answering({"/api/v1/repos/o/r/pulls/7": PULL}, []),
    )
    assert forge.state(ON_FORGEJO).origin == origin


def test_close_refuses_unsupported_https_endpoint_before_fetching() -> None:
    seen: list[str] = []
    forge = ForgejoForge(
        "https://forge.test/prefix", "token", transport=answering({}, seen)
    )
    with pytest.raises(ForgeRejectedError):
        forge.state(ON_FORGEJO)
    assert not seen
