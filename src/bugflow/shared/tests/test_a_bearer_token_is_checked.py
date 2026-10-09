"""A bearer token, checked as an identity provider's JWT.

The provider is stood in for by a key made here: a token is accepted
when that key signed it, it names the issuer, is addressed to this
server, has not expired, and was issued to a client this server
expects. Each refusal is one of those failing.
"""

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from bugflow.shared.domain.errors import TokenRefusedError
from bugflow.shared.domain.values.caller import Caller
from bugflow.shared.infrastructure.jwt_bearer_token import (
    JwtBearerToken,
    published_keys,
)

ISSUER = "https://idp.example"
AUDIENCE = "a-server"
CLIENT = "a-client"

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(signer: Any = KEY, **claims: Any) -> str:
    """A token as the provider issues one, with ``claims`` replacing
    its own; a claim given as None is left out."""
    now = int(time.time())
    held = {
        "iss": ISSUER,
        "aud": [AUDIENCE],
        "sub": "312345",
        "client_id": CLIENT,
        "exp": now + 600,
        "iat": now,
        "roles": ["a-reader"],
        **claims,
    }
    return jwt.encode(
        {k: v for k, v in held.items() if v is not None},
        signer,
        algorithm="RS256",
    )


def verifier(roles_claim: str = "roles") -> JwtBearerToken:
    return JwtBearerToken(
        ISSUER,
        AUDIENCE,
        [CLIENT],
        key=lambda _: KEY.public_key(),
        roles_claim=roles_claim,
    )


def test_a_token_the_provider_signed_names_its_caller() -> None:
    assert verifier().verify(token()) == Caller(
        subject="312345", client=CLIENT, roles=frozenset({"a-reader"})
    )


def test_the_client_is_read_from_azp_where_client_id_is_absent() -> None:
    assert verifier().verify(token(client_id=None, azp=CLIENT)).client == (
        CLIENT
    )


def test_roles_are_read_from_the_claim_the_server_was_told() -> None:
    told = token(roles=None, groups=["a-writer"])
    assert verifier("groups").verify(told).roles == frozenset({"a-writer"})
    assert verifier("roles").verify(told).roles == frozenset()


def test_a_token_with_no_roles_names_a_caller_with_none() -> None:
    assert verifier().verify(token(roles=None)).roles == frozenset()


@pytest.mark.parametrize(
    ("refused", "claims", "signer"),
    [
        ("signed by another key", {}, OTHER_KEY),
        ("from another issuer", {"iss": "https://elsewhere"}, KEY),
        ("addressed to another server", {"aud": ["another-server"]}, KEY),
        ("expired", {"exp": int(time.time()) - 3600}, KEY),
        ("issued to a client not expected", {"client_id": "another"}, KEY),
        ("naming nobody", {"sub": None}, KEY),
        ("with roles that are no list", {"roles": "a-reader"}, KEY),
    ],
)
def test_a_token_is_refused_when_it_is(
    refused: str, claims: dict[str, Any], signer: Any
) -> None:
    with pytest.raises(TokenRefusedError):
        verifier().verify(token(signer, **claims))


def test_the_keys_are_found_where_the_provider_says_and_asked_for_once() -> (
    None
):
    asked: list[str] = []

    def published(issuer: str) -> dict[str, Any]:
        asked.append(issuer)
        return {"jwks_uri": "http://127.0.0.1:1/the/keys"}

    key = published_keys(ISSUER, published)
    assert asked == []

    # Nothing listens at the address, so each lookup fails, having
    # asked the provider where its keys are the first time only.
    for _ in range(2):
        with pytest.raises(jwt.PyJWTError):
            key(token())
    assert asked == [ISSUER]


@pytest.mark.parametrize(
    "failure", [OSError("no route"), KeyError("jwks_uri"), ValueError("no")]
)
def test_a_provider_that_cannot_be_asked_vouches_for_nobody(
    failure: Exception,
) -> None:
    def key(_: str) -> Any:
        raise failure

    checked = JwtBearerToken(ISSUER, AUDIENCE, [CLIENT], key, "roles")
    with pytest.raises(TokenRefusedError, match="keys could not be had"):
        checked.verify(token())
