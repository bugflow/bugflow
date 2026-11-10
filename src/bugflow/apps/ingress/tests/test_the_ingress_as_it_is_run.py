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
from datetime import UTC, datetime
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
from bugflow.apps.shared.deploying import deploying_over
from bugflow.apps.shared.temporal import TemporalSettings
from bugflow.apps.worker.pull_request import DEBOUNCE
from bugflow.forge.infrastructure.sqlalchemy_forge_facts import delivery
from bugflow.method.dtos.deploy_policies import (
    DeployPoliciesRequest,
    PolicyFile,
)
from bugflow.method.tests.policy_files import READ
from bugflow.review.domain.models.gnome_setting import GnomeSetting
from bugflow.review.infrastructure.sqlalchemy_gnome_settings import (
    SqlAlchemyGnomeSettings,
)
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
                    sa.select(journal.c.event_type, journal.c.build)
                    .select_from(
                        journal.join(
                            delivery, delivery.c.event_id == journal.c.event_id
                        )
                    )
                    .where(delivery.c.delivery_id == "d-nothing")
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


SITE = {
    path.replace("prose", "site"): text.replace("prose", "site")
    for path, text in READ.items()
}


def deployed(database_url: str, tenant: str, files: dict[str, str]) -> None:
    deploying_over(database_url, None, ()).deploy.execute(
        DeployPoliciesRequest(
            repository=f"example-org/{tenant}-policies",
            commit="c1",
            files=tuple(
                PolicyFile(path=path, text=text)
                for path, text in files.items()
            ),
            sent_by="a test",
            tenant=tenant,
        )
    )


def ingress_for_tenants(
    database_url: str,
) -> tuple[FastAPI, dict[str, FakeClient]]:
    """The ingress with another tenant listed, and a client for each
    namespace it connects to."""
    clients: dict[str, FakeClient] = {}

    async def connect(settings: TemporalSettings) -> Any:
        clients[settings.namespace] = FakeClient()
        return clients[settings.namespace]

    environ = environment(database_url) | {
        "TENANTS": "business-development=business-development/bd-queue"
    }
    return app_from_environment(environ, connect=connect), clients


def test_a_tenant_listed_with_no_deployment_is_not_connected_to(
    database_url: str,
) -> None:
    app, clients = ingress_for_tenants(database_url)
    with TestClient(app):
        pass
    assert set(clients) == {"default"}


def test_a_delivery_is_handed_to_the_tenant_whose_gnome_judges(
    database_url: str,
) -> None:
    """Site, business development's gnome, is set on the repository and
    prose, default's, is not, so the delivery starts a workflow in
    business development's namespace alone (ADR 011)."""
    deployed(database_url, "default", READ)
    deployed(database_url, "business-development", SITE)
    SqlAlchemyGnomeSettings(database_url).save(
        GnomeSetting(
            forge="github",
            repo="o/r",
            gnome="site",
            behaviour="observe",
            set_by="a test",
            set_at=datetime.now(UTC),
        )
    )
    app, clients = ingress_for_tenants(database_url)
    body = pull_request("opened")
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/github", content=body, headers=signed(body, "d-site")
        )
    assert response.status_code == 202
    assert set(clients) == {"default", "business-development"}
    assert clients["default"].started == []
    assert len(clients["business-development"].started) == 1


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
