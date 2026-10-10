"""Tests that start the API the way uvicorn does, from environment
variables, against a real database.

The route tests build the API by hand with in-memory parts. These
check the part they skip: that the settings are read, that a caller's
roles are read from the token claim the settings name, and that a
deployment sent through the real stack is kept and recorded.

Skipped unless DATABASE_URL names a Postgres server.
"""

import time
from typing import Any

import jwt
import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from bugflow.apps.api.api import REQUIRED, api_from_environment
from bugflow.method.tests.policy_files import READ
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.sqlalchemy_journal import journal

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
BUILD = "2" * 40
ROUTE = "/api/policy-deployments"


def environment(database_url: str) -> dict[str, str]:
    return {
        "API_ISSUER": "https://issuer.example",
        "API_AUDIENCE": "an-audience",
        "API_CLIENTS": "a-client, another-client",
        "API_ROLES_CLAIM": "the-roles",
        "POLICY_DEPLOYER_ROLE": "a-deployer",
        "DATABASE_URL": database_url,
        "BUILD_SHA": BUILD,
        "POLICY_CHECKS": "em-dash",
    }


def token(**claims: Any) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": "https://issuer.example",
            "aud": ["an-audience"],
            "sub": "412345",
            "client_id": "a-client",
            "exp": now + 600,
            "the-roles": ["a-deployer"],
            **claims,
        },
        KEY,
        algorithm="RS256",
    )


def api(database_url: str) -> TestClient:
    return TestClient(
        api_from_environment(
            environment(database_url), key=lambda _: KEY.public_key()
        )
    )


def body() -> dict[str, object]:
    return {
        "repository": "example-org/pull-request-policies",
        "commit": "c1",
        "files": [{"path": p, "text": t} for p, t in READ.items()],
    }


@pytest.mark.parametrize("name", REQUIRED)
def test_the_api_does_not_start_without_each_required_setting(
    name: str,
) -> None:
    environ = environment("postgresql://nowhere/none")
    del environ[name]
    with pytest.raises(ValueError, match=name):
        api_from_environment(environ, key=lambda _: KEY.public_key())


def test_a_malformed_build_stops_the_api() -> None:
    environ = environment("postgresql://nowhere/none") | {"BUILD_SHA": "v1"}
    with pytest.raises(ValueError, match="BUILD_SHA"):
        api_from_environment(environ, key=lambda _: KEY.public_key())


def test_a_deployment_through_the_real_stack_is_kept_and_recorded(
    database_url: str,
) -> None:
    client = api(database_url)
    headers = {"Authorization": f"Bearer {token()}"}
    posted = client.post(ROUTE, json=body(), headers=headers)
    assert posted.status_code == 200, posted.text
    assert posted.json()["outcome"] == "deployed"
    read = client.get(f"{ROUTE}/in-force", headers=headers)
    assert read.json() == posted.json()["in_force"]
    engine = sa.create_engine(engine_url(database_url))
    try:
        with engine.connect() as connection:
            rows = list(
                connection.execute(
                    sa.select(journal.c.event_type, journal.c.build)
                )
            )
    finally:
        engine.dispose()
    assert rows == [("policies.deployed", BUILD)]


def test_the_roles_are_read_from_the_claim_the_settings_name(
    database_url: str,
) -> None:
    client = api(database_url)
    other_claim = token(**{"the-roles": [], "groups": ["a-deployer"]})
    refused = client.post(
        ROUTE,
        json=body(),
        headers={"Authorization": f"Bearer {other_claim}"},
    )
    assert refused.status_code == 403


def test_a_token_for_another_client_is_refused(database_url: str) -> None:
    client = api(database_url)
    refused = client.post(
        ROUTE,
        json=body(),
        headers={"Authorization": f"Bearer {token(client_id='laptop')}"},
    )
    assert refused.status_code == 401
