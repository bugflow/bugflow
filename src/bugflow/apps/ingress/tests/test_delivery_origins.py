"""Deliveries retain their source without rewriting old events."""

import json
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import uuid4

import httpx2
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from bugflow.apps.ingress.ingress import create_app
from bugflow.apps.ingress.tests.test_webhook_ingress import (
    SECRET,
    FakeEvaluations,
    FixedClock,
    pull_request,
    signed,
)
from bugflow.apps.shared.journals import delivery_journal
from bugflow.forge.domain.models.delivery import Delivery
from bugflow.forge.domain.models.polling import (
    PolledComment,
    PolledPullRequest,
)
from bugflow.forge.infrastructure.signatures import digest
from bugflow.forge.infrastructure.webhook_sink import SignedWebhookSink
from bugflow.forge.tests.journal import QueryableJournal
from bugflow.forge.usecases.poll_pull_requests import (
    delivery_for,
    delivery_for_comment,
)
from bugflow.forge.usecases.receive_delivery import ReceiveDeliveryUseCase
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.sqlalchemy_repository_associations import (
    SqlAlchemyRepositoryAssociations,
)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
@pytest.mark.parametrize("action", ["opened", "labeled", "closed", "dismiss"])
def test_delivery_facts_are_associated_together(
    backend: str, action: str, request: pytest.FixtureRequest
) -> None:
    journal: Any
    associations: Any
    if backend == "postgres":
        url = request.getfixturevalue("database_url")
        journal = delivery_journal(url, None)
        associations = SqlAlchemyRepositoryAssociations(url)
    else:
        journal = QueryableJournal()
        associations = journal._associations
    client = TestClient(
        create_app(
            SECRET,
            receive=ReceiveDeliveryUseCase(
                journal, FixedClock(), FakeEvaluations()
            ),
        )
    )
    body_dict = json.loads(pull_request(action))
    if action == "closed":
        body_dict["pull_request"] = {"merged": True, "merge_commit_sha": "sha"}
    if action == "dismiss":
        body_dict.update(
            action="created",
            issue={"number": 6, "pull_request": {}},
            comment={
                "id": 5,
                "body": "/dismiss ED-01 reason",
                "user": {"login": "member"},
            },
        )
    body = json.dumps(body_dict).encode()
    delivery_id = str(uuid4())
    headers = signed(body, delivery_id)
    if action == "dismiss":
        headers["X-GitHub-Event"] = "issue_comment"
    response = client.post("/webhooks/github", content=body, headers=headers)
    assert response.status_code == 202
    if backend == "postgres":
        from bugflow.shared.infrastructure.sqlalchemy_journal import (
            journal as table,
        )

        engine = sa.create_engine(
            engine_url(request.getfixturevalue("database_url"))
        )
        with engine.connect() as connection:
            ids = (
                connection.execute(
                    sa.select(table.c.event_id).where(
                        table.c.payload["delivery_id"].astext == delivery_id
                    )
                )
                .scalars()
                .all()
            )
    else:
        ids = [e.event_id for e in journal.entries]
    assert len(ids) == (2 if action in ("closed", "dismiss") else 1)
    assert all(
        str(associations.origin_for("journal", str(i))) == "github.com/o/r"
        for i in ids
    )


@pytest.mark.parametrize(
    "endpoint, expected",
    [
        ("https://FORGE.test:8443/", "forge.test:8443/o/r"),
        ("http://forge.test", None),
        (None, None),
    ],
)
def test_forgejo_uses_configured_endpoint_not_payload_urls(
    endpoint: str | None, expected: str | None
) -> None:
    journal = QueryableJournal()
    client = TestClient(
        create_app(
            SECRET,
            forgejo_url=endpoint,
            receive=ReceiveDeliveryUseCase(
                journal, FixedClock(), FakeEvaluations()
            ),
        )
    )
    payload = json.loads(pull_request("labeled"))
    payload["repository"]["html_url"] = "https://attacker.test/o/r"
    payload["_bugflow_origin"] = "attacker.test/o/r"
    body = json.dumps(payload).encode()
    response = client.post(
        "/webhooks/forgejo",
        content=body,
        headers={
            "X-Forgejo-Event": "pull_request",
            "X-Forgejo-Delivery": "d",
            "X-Forgejo-Signature": digest(SECRET.encode(), body),
        },
    )
    assert response.status_code == 202
    assert journal._origin(journal.entries[0].event_id) == expected


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://forge.test/prefix",
        "https://user:secret@forge.test",
        "https://forge.test?query",
    ],
)
def test_invalid_https_endpoint_refuses_startup(endpoint: str) -> None:
    with pytest.raises(ValueError):
        create_app(SECRET, forgejo_url=endpoint)


@pytest.mark.parametrize("origin", [None, "github.com/o/r", "other.test/o/r"])
@pytest.mark.parametrize("comment", [False, True])
def test_polled_origin_survives_signed_transport(
    origin: str | None, comment: bool
) -> None:
    journal = QueryableJournal()
    client = TestClient(
        create_app(
            SECRET,
            receive=ReceiveDeliveryUseCase(
                journal, FixedClock(), FakeEvaluations()
            ),
        )
    )
    ref = PullRequestRef(owner="o", repo="r", number=6)
    now = FixedClock().now()
    if comment:
        delivery = delivery_for_comment(
            PolledComment(
                ref=ref,
                origin=origin,
                comment_id=5,
                author="member",
                body="/dismiss ED-01 reason",
                updated_at=now,
            )
        )
        assert delivery is not None
    else:
        delivery = delivery_for(
            PolledPullRequest(
                ref=ref,
                origin=origin,
                open=True,
                head_sha="sha",
                title="title",
                body="",
                updated_at=now,
            )
        )

    def transport(outgoing: httpx2.Request) -> httpx2.Response:
        response = client.post(
            outgoing.url.path,
            content=outgoing.content,
            headers=dict(outgoing.headers),
        )
        return httpx2.Response(response.status_code, json=response.json())

    sink = SignedWebhookSink(
        "http://ingress.test", SECRET, httpx2.MockTransport(transport)
    )
    if origin == "other.test/o/r":
        from bugflow.forge.domain.errors import DeliveryNotAcceptedError

        with pytest.raises(DeliveryNotAcceptedError, match="400"):
            sink.send(delivery)
        assert not journal.entries
    else:
        sink.send(delivery)
        assert journal.entries
        assert all(
            journal._origin(e.event_id) == origin for e in journal.entries
        )


def test_old_delivery_retry_is_not_assigned_an_origin() -> None:
    journal = QueryableJournal()
    use_case = ReceiveDeliveryUseCase(journal, FixedClock(), FakeEvaluations())
    from bugflow.forge.dtos.receive_delivery import ReceiveDeliveryRequest

    use_case.execute(
        ReceiveDeliveryRequest(
            delivery=Delivery(
                forge="github",
                delivery_id="old",
                event="push",
                action=None,
                repository="o/r",
                ref=None,
            )
        )
    )
    client = TestClient(create_app(SECRET, receive=use_case))
    body = pull_request()
    response = client.post(
        "/webhooks/github", content=body, headers=signed(body, "old")
    )
    assert response.json()["outcome"] == "duplicate"
    assert len(journal.entries) == 1
    assert journal._origin(journal.entries[0].event_id) is None


@pytest.mark.parametrize("backend", ["memory", "postgres"])
def test_poll_coverage_requires_the_same_origin(
    backend: str, request: pytest.FixtureRequest
) -> None:
    from bugflow.forge.tests.test_journal_queries_in_postgres import (
        AT,
        entry,
        unique_ref,
    )

    journal: Any
    if backend == "postgres":
        url = request.getfixturevalue("database_url")
        journal = delivery_journal(url, None)
    else:
        journal = QueryableJournal()
    ref = unique_ref()
    origin = f"one.test/{ref.owner}/{ref.repo}"
    journal.append([replace(entry("delivery.received", ref), origin=origin)])
    assert journal.received_since(ref, AT, origin=origin)
    assert not journal.received_since(
        ref, AT, origin=f"two.test/{ref.owner}/{ref.repo}"
    )
    assert not journal.received_since(
        ref, AT + timedelta(seconds=1), origin=origin
    )
    unresolved = unique_ref()
    journal.append([entry("delivery.received", unresolved)])
    assert not journal.received_since(
        unresolved, AT, origin=f"one.test/{unresolved.owner}/{unresolved.repo}"
    )


@pytest.mark.parametrize("first_origin", [None, "other.test/o/r"])
def test_existing_unresolved_or_foreign_run_refuses_new_webhook(
    first_origin: str | None,
) -> None:
    from bugflow.forge.tests.test_journal_queries_in_postgres import entry

    ref = PullRequestRef(owner="o", repo="r", number=6)
    journal = QueryableJournal()
    held = replace(
        entry("delivery.received", ref),
        workflow_id="pr/github/o/r/6",
        run_id="run-1",
        origin=first_origin,
    )
    journal.append([held])
    client = TestClient(
        create_app(
            SECRET,
            receive=ReceiveDeliveryUseCase(
                journal, FixedClock(), FakeEvaluations()
            ),
        )
    )
    body = pull_request()
    response = client.post(
        "/webhooks/github", content=body, headers=signed(body)
    )
    assert response.status_code == 409
    assert [e.event_id for e in journal.entries] == [held.event_id]
    assert journal._origin(held.event_id) == first_origin


def test_old_poller_cannot_inherit_a_known_run_origin() -> None:
    journal = QueryableJournal()
    client = TestClient(
        create_app(
            SECRET,
            receive=ReceiveDeliveryUseCase(
                journal, FixedClock(), FakeEvaluations()
            ),
        )
    )
    body = pull_request()
    assert (
        client.post(
            "/webhooks/github", content=body, headers=signed(body)
        ).status_code
        == 202
    )
    response = client.post(
        "/webhooks/github", content=body, headers=signed(body, "poll-old")
    )
    assert response.status_code == 409
    assert len(journal.entries) == 1


def test_poll_origin_is_covered_by_signature() -> None:
    journal = QueryableJournal()
    client = TestClient(
        create_app(
            SECRET,
            receive=ReceiveDeliveryUseCase(
                journal, FixedClock(), FakeEvaluations()
            ),
        )
    )
    payload = json.loads(pull_request()) | {"_bugflow_origin": None}
    original = json.dumps(payload).encode()
    changed = json.dumps(
        payload | {"_bugflow_origin": "github.com/o/r"}
    ).encode()
    response = client.post(
        "/webhooks/github",
        content=changed,
        headers=signed(original, "poll-tampered"),
    )
    assert response.status_code == 401
    assert not journal.entries


def test_environment_configures_forgejo_provenance() -> None:
    from bugflow.apps.ingress.ingress import IngressParts, app_from_environment

    journal = QueryableJournal()
    app = app_from_environment(
        {
            "DATABASE_URL": "postgresql://unused/db",
            "WEBHOOK_SECRET": SECRET,
            "FORGEJO_URL": "https://forge.test",
        },
        parts=IngressParts(),
    )
    app.state.receive = ReceiveDeliveryUseCase(
        journal, FixedClock(), FakeEvaluations()
    )
    body = pull_request("labeled")
    response = TestClient(app).post(
        "/webhooks/forgejo",
        content=body,
        headers={
            "X-Forgejo-Event": "pull_request",
            "X-Forgejo-Delivery": "environment",
            "X-Forgejo-Signature": digest(SECRET.encode(), body),
        },
    )
    assert response.status_code == 202
    assert journal._origin(journal.entries[0].event_id) == "forge.test/o/r"
