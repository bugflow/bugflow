"""Each request to GitHub is signed with the token for the repository's
owner, since a fine-grained token belongs to one organisation."""

import httpx2
import pytest

from bugflow.forge.domain.errors import ForgeRejectedError
from bugflow.forge.infrastructure.github import GitHubForge, GitHubTokens
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


def recording(seen: list[tuple[str, str]]) -> httpx2.MockTransport:
    def answer(request: httpx2.Request) -> httpx2.Response:
        seen.append(
            (request.url.path, request.headers.get("Authorization", ""))
        )
        return httpx2.Response(200, json={"state": "open"})

    return httpx2.MockTransport(answer)


def test_an_owner_s_token_signs_its_requests_and_others_the_default() -> None:
    seen: list[tuple[str, str]] = []
    forge = GitHubForge(
        GitHubTokens(any_owner="any", by_owner={"initech": "theirs"}),
        recording(seen),
    )
    forge.is_open(PullRequestRef(owner="initech", repo="permits", number=1))
    forge.is_open(PullRequestRef(owner="acme", repo="office", number=2))
    assert seen == [
        ("/repos/initech/permits/pulls/1", "Bearer theirs"),
        ("/repos/acme/office/pulls/2", "Bearer any"),
    ]


def test_an_owner_with_no_token_is_refused_before_anything_is_sent() -> None:
    seen: list[tuple[str, str]] = []
    forge = GitHubForge(
        GitHubTokens(by_owner={"initech": "theirs"}), recording(seen)
    )
    with pytest.raises(ForgeRejectedError, match="acme=TOKEN"):
        forge.is_open(PullRequestRef(owner="acme", repo="office", number=2))
    assert seen == []


def test_an_owner_s_name_is_read_without_regard_to_case() -> None:
    tokens = GitHubTokens(by_owner={"initech": "theirs"})
    assert tokens.for_owner("INITECH") == "theirs"
