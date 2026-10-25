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
            "archive_journal",
            "forge_journal",
            "review_journal",
            "stocktake_journal",
            "policy_journal",
            "archive_binding",
            "archive_event",
            "archive_block_put",
            "archive_index_file",
            "archive_index_line",
            "archive_index_position",
            "bugflow_schema_version",
            "pull_request_snapshot",
            "judge_exchange",
            "agent_write_up",
            "review_governance",
            "repository_enforcement",
            "repository_association",
            "repository_withholding",
            "spend_binding",
            "repository_judged_policy",
            "repository_dispatched_process",
            "repository_layer_boundary",
            "cadence_boundary",
            "policy_deployment",
            "policy_deployment_file",
            "policy_deployment_in_force",
            "forge",
            "repository",
            "repository_name",
            "pull_request",
            "workflow",
            "workflow_run",
            "archive_seal",
            "archive_seal_claim",
            "archive_registration",
            "archive_registration_beside",
            "archive_refusal",
            "delivery",
            "webhook_reconciliation",
            "webhook_reconciliation_event",
            "pull_request_observation",
            "pull_request_observation_delivery",
            "pull_request_observation_component",
            "pull_request_observation_agent",
            "pull_request_observation_policy",
            "pull_request_observation_commit",
            "pull_request_closure",
            "pull_request_closure_outstanding",
            "pull_request_merge",
            "reaction",
            "reaction_agent",
            "finding_dismissal",
            "review_action",
            "review_action_removed_label",
            "agent_dispatch",
            "agent_dispatch_withheld_file",
            "raised_finding",
            "resolved_finding",
            "rewritten_finding",
            "withheld_finding",
            "judge_invocation",
            "judge_invocation_unsupported",
            "model_call",
            "model_call_finish_reason",
            "model_call_object",
            "policy_check",
            "review_grade",
            "completion",
            "stocktake",
            "stocktake_pull_request",
            "stocktake_dispatch",
            "stocktake_review",
            "stocktake_finding",
            "stocktake_grade",
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
