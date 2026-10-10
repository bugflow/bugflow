"""Tests that start the ingress the way uvicorn does, from environment
variables, against a real database and a fake Temporal client.

The route tests build the ingress by hand with in-memory parts. These
check the part they skip: that the settings are read, and that a server
with nothing installed, which this package is until a deployment is put
in force, starts, answers its healthcheck, journals a delivery and hands
one to the worker.

Skipped unless DATABASE_URL names a Postgres server.
"""

import hashlib
import hmac
import json
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bugflow.apps.ingress.ingress import (
    REQUIRED,
    IngressParts,
    app_from_environment,
)
from bugflow.apps.shared.temporal import TemporalSettings
from bugflow.apps.worker.pull_request import DEBOUNCE
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.sqlalchemy_journal import journal

SECRET = "test-secret"
BUILD = "3" * 40


class FakeHandle:
    id = "pr/github/o/r/6"
    result_run_id = "run-1"


class FakeClient:
    """A Temporal client that remembers what it was asked to start."""

    def __init__(self) -> None:
        self.started: list[Any] = []

    async def start_workflow(
        self, run: Any, arg: Any, **kwargs: Any
    ) -> FakeHandle:
        self.started.append(arg)
        return FakeHandle()


def environment(database_url: str) -> dict[str, str]:
    return {
        "WEBHOOK_SECRET": SECRET,
        "DATABASE_URL": database_url,
        "BUILD_SHA": BUILD,
        "TEMPORAL_TASK_QUEUE": "a-queue",
    }


def ingress(
    database_url: str, parts: IngressParts | None = None
) -> tuple[FastAPI, FakeClient]:
    client = FakeClient()

    async def connect(settings: TemporalSettings) -> Any:
        assert settings.task_queue == "a-queue"
        return client

    return app_from_environment(
        environment(database_url), parts, connect=connect
    ), client


def pull_request(action: str) -> bytes:
    return json.dumps(
        {
            "action": action,
            "number": 6,
            "repository": {"name": "r", "owner": {"login": "o"}},
        }
    ).encode()


def signed(body: bytes, delivery_id: str) -> dict[str, str]:
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": f"sha256={digest}",
        "Content-Type": "application/json",
    }


@pytest.mark.parametrize("name", REQUIRED)
def test_the_ingress_does_not_start_without_each_required_setting(
    name: str,
) -> None:
    environ = environment("postgresql://nowhere/none")
    del environ[name]
    with pytest.raises(ValueError, match=name):
        app_from_environment(environ)


def test_a_malformed_build_stops_the_ingress() -> None:
    environ = environment("postgresql://nowhere/none") | {"BUILD_SHA": "v1"}
    with pytest.raises(ValueError, match="BUILD_SHA"):
        app_from_environment(environ)


def test_a_server_with_nothing_installed_starts_and_answers(
    database_url: str,
) -> None:
    app, _ = ingress(database_url)
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}


def test_a_delivery_it_does_nothing_with_is_journalled_with_the_build(
    database_url: str,
) -> None:
    app, temporal = ingress(database_url)
    body = pull_request("labeled")
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/github", content=body, headers=signed(body, "d-nothing")
        )
    assert response.status_code == 202
    assert response.json()["outcome"] == "ignored"
    assert temporal.started == []
    engine = sa.create_engine(engine_url(database_url))
    try:
        with engine.connect() as connection:
            rows = list(
                connection.execute(
                    sa.select(journal.c.event_type, journal.c.build).where(
                        journal.c.payload["delivery_id"].astext == "d-nothing"
                    )
                )
            )
    finally:
        engine.dispose()
    assert rows == [("delivery.received", BUILD)]


def test_a_delivery_is_handed_to_the_worker_with_the_default_window(
    database_url: str,
) -> None:
    """With no deployment in force there are no layers, so no repository
    has declared a settling window, and the workflow waits its default."""
    app, temporal = ingress(database_url)
    body = pull_request("opened")
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/github", content=body, headers=signed(body, "d-opened")
        )
    assert response.status_code == 202
    assert response.json()["workflow_id"] == "pr/github/o/r/6"
    (input,) = temporal.started
    assert input.debounce_seconds == DEBOUNCE.total_seconds()


def test_the_parts_another_server_adds_are_used(database_url: str) -> None:
    instrumented: list[FastAPI] = []
    built: list[Any] = []

    def corpora(client: Any, settings: TemporalSettings, loop: Any) -> Any:
        built.append(client)
        return object()

    app, temporal = ingress(
        database_url,
        IngressParts(corpora=corpora, instrument=instrumented.append),
    )
    assert instrumented == [app]
    with TestClient(app):
        pass
    assert built == [temporal]
