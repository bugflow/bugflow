"""Tests of how GitHub lists an owner's repositories for discovery,
against a stand-in for its API."""

import httpx2
import pytest

from bugflow.forge.domain.errors import ForgeRejectedError
from bugflow.forge.domain.models.forge_repository import ListedRepository
from bugflow.forge.infrastructure.github import GitHubForge, GitHubTokens


def answering(
    routes: dict[str, list[dict[str, object]]],
    accounts: dict[str, str],
    me: str = "the-server",
) -> httpx2.MockTransport:
    """GitHub, holding ``routes`` and each account's type by login, and
    answering ``/user`` as ``me``, whom the token signs in as."""

    def handle(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/user":
            return httpx2.Response(200, json={"login": me})
        login = path.removeprefix("/users/")
        if login in accounts:
            return httpx2.Response(200, json={"type": accounts[login]})
        found = routes.get(path)
        if found is None:
            return httpx2.Response(403, json={"message": "Forbidden"})
        page = int(request.url.params.get("page", "1"))
        return httpx2.Response(200, json=found if page == 1 else [])

    return httpx2.MockTransport(handle)


def test_an_organisations_repositories_are_listed_with_their_keys() -> None:
    transport = answering(
        {
            "/orgs/gs-gs/repos": [
                {"id": 11, "full_name": "gs-gs/one", "archived": False},
                {
                    "id": 12,
                    "full_name": "gs-gs/two",
                    "archived": True,
                    "private": True,
                },
            ]
        },
        {"gs-gs": "Organization"},
    )
    forge = GitHubForge(GitHubTokens(by_owner={"gs-gs": "t"}), transport)
    assert forge.repositories_of("gs-gs") == [
        ListedRepository(forge="github", name="gs-gs/one", forge_key="11"),
        ListedRepository(
            forge="github",
            name="gs-gs/two",
            forge_key="12",
            archived=True,
            private=True,
        ),
    ]


def test_an_owner_that_is_no_organisation_is_listed_as_a_user() -> None:
    transport = answering(
        {"/users/someone/repos": [{"id": 21, "full_name": "someone/tool"}]},
        {"someone": "User"},
    )
    forge = GitHubForge("t", transport)
    assert [one.name for one in forge.repositories_of("someone")] == [
        "someone/tool"
    ]


def test_a_user_whose_own_token_it_is_has_private_ones_listed() -> None:
    """GitHub shows a user's private repositories only to that user, so
    with the user's own token they are listed as the user."""
    transport = answering(
        {
            "/user/repos": [
                {"id": 41, "full_name": "someone/open"},
                {"id": 42, "full_name": "someone/closed", "private": True},
            ],
            "/users/someone/repos": [{"id": 41, "full_name": "someone/open"}],
        },
        {"someone": "User"},
        me="Someone",
    )
    forge = GitHubForge(GitHubTokens(by_owner={"someone": "t"}), transport)
    assert [
        (one.name, one.private) for one in forge.repositories_of("someone")
    ] == [
        ("someone/open", False),
        ("someone/closed", True),
    ]


def test_an_organisation_that_refuses_the_token_is_a_failure() -> None:
    transport = answering(
        {"/users/gs-gs/repos": [{"id": 31, "full_name": "gs-gs/public"}]},
        {"gs-gs": "Organization"},
    )
    forge = GitHubForge("t", transport)
    with pytest.raises(ForgeRejectedError):
        forge.repositories_of("gs-gs")


def test_an_owners_listing_is_signed_with_the_owners_token() -> None:
    tokens = GitHubTokens(any_owner="any", by_owner={"gs-gs": "own"})
    assert tokens.for_path("/orgs/gs-gs/repos") == "own"
    assert tokens.for_path("/users/other/repos") == "any"
