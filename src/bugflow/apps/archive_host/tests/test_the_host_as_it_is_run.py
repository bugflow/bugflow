"""Tests that start the archive host the way uvicorn does, from environment
variables, against a real database.

The protocol test builds the host by hand with in-memory parts. These tests
check the part it skips: that the settings are read, that the scripts are
run at start-up, and that a caller's roles are read from the token
claim the settings name.

Skipped unless DATABASE_URL names a Postgres server.
"""

import time
from typing import Any

import jwt
import sqlalchemy as sa
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from bugflow.apps.archive_host.host import from_environment
from bugflow.shared.infrastructure.database import engine_url

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
UNBOUND = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


def environment(database_url: str) -> dict[str, str]:
    return {
        "ARCHIVE_ISSUER": "https://issuer.example",
        "ARCHIVE_AUDIENCE": "an-audience",
        "ARCHIVE_CLIENTS": "a-client",
        "ARCHIVE_ROLES_CLAIM": "the-roles",
        "ARCHIVE_READER_ROLE": "a-reader",
        "ARCHIVE_WRITER_ROLE": "a-writer",
        "ARCHIVE_S3_ENDPOINT": "https://objects.example",
        "ARCHIVE_S3_BUCKET": "a-bucket",
        "ARCHIVE_S3_ACCESS_KEY": "an-access-key",
        "ARCHIVE_S3_SECRET_KEY": "a-secret-key",
        "DATABASE_URL": database_url,
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
            **claims,
        },
        KEY,
        algorithm="RS256",
    )


def asked(client: TestClient, held: str) -> tuple[int, str]:
    answered = client.get(
        "/",
        headers={
            "Host": f"{UNBOUND}.archive.example",
            "Authorization": f"Bearer {held}",
        },
    )
    return answered.status_code, answered.json()["refused"]


def test_the_host_runs_the_scripts_when_it_starts(database_url: str) -> None:
    app = from_environment(
        environment(database_url), key=lambda _: KEY.public_key()
    )
    engine = sa.create_engine(engine_url(database_url))
    try:
        assert sa.inspect(engine).get_table_names() == []
        with TestClient(app):
            pass
        assert set(sa.inspect(engine).get_table_names()) == {
            "journal",
            "archive_bindings",
            "archive_events",
            "archive_block_puts",
            "archive_index_files",
            "archive_index_lines",
            "archive_index_positions",
            "bugflow_schema_version",
            "pull_request_snapshots",
            "judge_exchanges",
            "agent_write_ups",
            "review_governance",
            "repository_enforcement",
            "repository_withholding",
            "spend_bindings",
            "repository_judged_policies",
            "repository_dispatched_processes",
            "repository_layer_boundaries",
            "cadence_boundaries",
        }
    finally:
        engine.dispose()


def test_a_caller_s_roles_are_read_from_the_claim_the_environment_names(
    database_url: str,
) -> None:
    app = from_environment(
        environment(database_url), key=lambda _: KEY.public_key()
    )
    with TestClient(app) as client:
        # A reader is let through to a ledger nobody bound, which the
        # database then says is not kept.
        assert asked(client, token(**{"the-roles": ["a-reader"]})) == (
            404,
            "absent",
        )
        # The same role under another claim grants nothing.
        assert asked(client, token(roles=["a-reader"])) == (403, "access")
