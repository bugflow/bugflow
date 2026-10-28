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
) -> httpx2.MockTransport:
    """GitHub, holding ``routes`` and each account's type by login."""

    def handle(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
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
            "/orgs/acme/repos": [
                {"id": 11, "full_name": "acme/one", "archived": False},
                {
                    "id": 12,
                    "full_name": "acme/two",
                    "archived": True,
                    "private": True,
                },
            ]
        },
        {"acme": "Organization"},
    )
    forge = GitHubForge(GitHubTokens(by_owner={"acme": "t"}), transport)
    assert forge.repositories_of("acme") == [
        ListedRepository(forge="github", name="acme/one", forge_key="11"),
        ListedRepository(
            forge="github",
            name="acme/two",
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


def test_an_organisation_that_refuses_the_token_is_a_failure() -> None:
    transport = answering(
        {"/users/acme/repos": [{"id": 31, "full_name": "acme/public"}]},
        {"acme": "Organization"},
    )
    forge = GitHubForge("t", transport)
    with pytest.raises(ForgeRejectedError):
        forge.repositories_of("acme")


def test_an_owners_listing_is_signed_with_the_owners_token() -> None:
    tokens = GitHubTokens(any_owner="any", by_owner={"acme": "own"})
    assert tokens.for_path("/orgs/acme/repos") == "own"
    assert tokens.for_path("/users/other/repos") == "any"
