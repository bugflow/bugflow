"""A GitHub App signs its requests with an installation token, minted
for each owner it is installed on and minted again before it expires,
so that GitHub attributes what the server does to the App's bot."""

from datetime import UTC, datetime, timedelta

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from bugflow.forge.domain.errors import ForgeRejectedError
from bugflow.forge.infrastructure.github import GitHubForge, GitHubTokens
from bugflow.forge.infrastructure.github_app import (
    RENEW_BEFORE_SECONDS,
    GitHubApp,
    InstallationTokens,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_PEM = KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
PUBLIC_PEM = (
    KEY.public_key()
    .public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)

APP = GitHubApp(
    app_id="4242", private_key=PRIVATE_PEM, installations={"gs-gs": 77}
)

START = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.at = START

    def __call__(self) -> float:
        return self.at.timestamp()


class FakeGitHub:
    """Answers a mint with a token that names how many were minted, and
    records every request's path and authorization."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.seen: list[tuple[str, str]] = []
        self.minted = 0

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self)

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.seen.append(
            (request.url.path, request.headers.get("Authorization", ""))
        )
        if request.url.path.endswith("/access_tokens"):
            self.minted += 1
            expires = self.clock.at + timedelta(hours=1)
            return httpx2.Response(
                201,
                json={
                    "token": f"ghs_{self.minted}",
                    "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )
        return httpx2.Response(200, json={"state": "open"})


def test_a_token_is_minted_with_a_jwt_the_app_s_key_signs() -> None:
    clock = Clock()
    github = FakeGitHub(clock)
    tokens = InstallationTokens(APP, github.transport(), now=clock)

    assert tokens.for_owner("gs-gs") == "ghs_1"
    path, authorization = github.seen[0]
    assert path == "/app/installations/77/access_tokens"
    scheme, _, signed = authorization.partition(" ")
    assert scheme == "Bearer"
    # The fake clock is not the real one, so the dates are read and not
    # checked against now.
    claims = jwt.decode(
        signed,
        PUBLIC_PEM,
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims["iss"] == "4242"
    assert claims["iat"] < clock() < claims["exp"] <= clock() + 10 * 60


def test_a_token_is_held_until_it_is_about_to_expire() -> None:
    clock = Clock()
    github = FakeGitHub(clock)
    tokens = InstallationTokens(APP, github.transport(), now=clock)

    assert tokens.for_owner("gs-gs") == "ghs_1"
    clock.at += timedelta(minutes=30)
    assert tokens.for_owner("GS-GS") == "ghs_1"
    clock.at += timedelta(hours=1) - timedelta(
        minutes=30, seconds=RENEW_BEFORE_SECONDS - 1
    )
    assert tokens.for_owner("gs-gs") == "ghs_2"
    assert github.minted == 2


def test_an_owner_the_app_is_not_installed_on_is_refused_unsent() -> None:
    clock = Clock()
    github = FakeGitHub(clock)
    tokens = InstallationTokens(APP, github.transport(), now=clock)
    with pytest.raises(ForgeRejectedError, match="gs-dawr=INSTALLATION_ID"):
        tokens.for_owner("gs-dawr")
    assert github.seen == []
    assert not tokens.holds("gs-dawr")
    assert tokens.owners == frozenset({"gs-gs"})


def test_github_refusing_the_mint_is_a_rejection_that_says_why() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            401, json={"message": "A JSON web token could not be decoded"}
        )

    tokens = InstallationTokens(APP, httpx2.MockTransport(refuse))
    with pytest.raises(ForgeRejectedError, match=r"401.*could not be decoded"):
        tokens.for_owner("gs-gs")


def test_the_forge_signs_an_installed_owner_s_requests_with_its_token() -> (
    None
):
    clock = Clock()
    github = FakeGitHub(clock)
    held = GitHubTokens(
        any_owner="any",
        by_owner={"gs-dawr": "dawr"},
        app=InstallationTokens(APP, github.transport(), now=clock),
    )
    forge = GitHubForge(held, github.transport())

    forge.is_open(PullRequestRef(owner="gs-gs", repo="office", number=1))
    forge.is_open(PullRequestRef(owner="gs-dawr", repo="permits", number=2))
    forge.is_open(PullRequestRef(owner="other", repo="thing", number=3))
    assert [one for one in github.seen if "/pulls/" in one[0]] == [
        ("/repos/gs-gs/office/pulls/1", "Bearer ghs_1"),
        ("/repos/gs-dawr/permits/pulls/2", "Bearer dawr"),
        ("/repos/other/thing/pulls/3", "Bearer any"),
    ]
    assert held.owners == frozenset({"gs-gs", "gs-dawr"})


def test_an_owner_s_own_token_is_used_before_the_app_s() -> None:
    clock = Clock()
    github = FakeGitHub(clock)
    held = GitHubTokens(
        by_owner={"gs-gs": "own"},
        app=InstallationTokens(APP, github.transport(), now=clock),
    )
    assert held.for_owner("gs-gs") == "own"
    assert github.minted == 0


def test_the_app_alone_signs_a_request_that_names_no_owner() -> None:
    clock = Clock()
    github = FakeGitHub(clock)
    held = GitHubTokens(
        app=InstallationTokens(APP, github.transport(), now=clock)
    )
    assert held.for_path("/rate_limit") == "ghs_1"
    assert held.owners == frozenset({"gs-gs"})
