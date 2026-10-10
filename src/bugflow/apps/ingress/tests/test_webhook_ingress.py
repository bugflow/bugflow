"""The webhook ingress: signatures, routing, and answering at once.

Driven through FastAPI's test client, with the real receive-delivery use
case over the in-memory journal and a fake evaluation starter.
"""

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from standardwebhooks import Webhook

import bugflow.forge.tests
from bugflow.apps.ingress.ingress import app_from_environment, create_app
from bugflow.forge.domain.errors import EvaluationStartError
from bugflow.forge.tests.journal import QueryableJournal
from bugflow.forge.usecases.receive_delivery import ReceiveDeliveryUseCase
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.models.journal_entry import (
    event_id as make_event_id,
)
from bugflow.shared.domain.values.acknowledgement import Acknowledgement
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.work.tests.journal import QueryableJournal as WorkJournal
from bugflow.work.usecases.receive_completion import ReceiveCompletionUseCase

SECRET = "test-secret"
REVIEW_SECRET = "whsec_" + ("c" * 32)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 11, tzinfo=UTC)


class FakeEvaluations:
    def __init__(self, fail: bool = False) -> None:
        self.started: list[str] = []
        self.fail = fail

    def start(self, ref: PullRequestRef, delivery_id: str) -> Correlation:
        if self.fail:
            raise EvaluationStartError("Temporal is unreachable")
        self.started.append(delivery_id)
        return Correlation(workflow_id="pr/github/o/r/6", run_id="run-1")

    def close(
        self, ref: PullRequestRef, delivery_id: str, merged: bool = False
    ) -> Correlation | None:
        return None


def client_with(
    evaluations: FakeEvaluations,
) -> tuple[TestClient, QueryableJournal]:
    journal = QueryableJournal()
    use_case = ReceiveDeliveryUseCase(journal, FixedClock(), evaluations)
    return TestClient(create_app(SECRET, receive=use_case)), journal


def pull_request(action: str = "opened") -> bytes:
    return json.dumps(
        {
            "action": action,
            "number": 6,
            "repository": {"name": "r", "owner": {"login": "o"}},
        }
    ).encode()


def signed(
    body: bytes, delivery_id: str = "d-1", secret: str = SECRET
) -> dict[str, str]:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": f"sha256={digest}",
        "Content-Type": "application/json",
    }


def post(client: TestClient, body: bytes, headers: dict[str, str]):  # type: ignore[no-untyped-def]
    return client.post("/webhooks/github", content=body, headers=headers)


def test_a_signed_opened_delivery_starts_an_evaluation_at_once() -> None:
    evaluations = FakeEvaluations()
    client, _ = client_with(evaluations)
    body = pull_request()
    response = post(client, body, signed(body))
    assert response.status_code == 202
    assert response.json() == {
        "delivery_id": "d-1",
        "outcome": "evaluate",
        "reason": "pull_request opened",
        "workflow_id": "pr/github/o/r/6",
        "run_id": "run-1",
    }
    assert evaluations.started == ["d-1"]


def test_a_delivery_signed_with_another_secret_is_rejected() -> None:
    evaluations = FakeEvaluations()
    client, journal = client_with(evaluations)
    body = pull_request()
    response = post(client, body, signed(body, secret="wrong"))
    assert response.status_code == 401
    assert journal.entries == [] and evaluations.started == []


def test_a_redelivery_is_a_duplicate() -> None:
    evaluations = FakeEvaluations()
    client, _ = client_with(evaluations)
    body = pull_request()
    post(client, body, signed(body))
    response = post(client, body, signed(body))
    assert (response.status_code, response.json()["outcome"]) == (
        202,
        "duplicate",
    )
    assert evaluations.started == ["d-1"]


def test_an_ignored_action_starts_nothing() -> None:
    evaluations = FakeEvaluations()
    client, _ = client_with(evaluations)
    body = pull_request(action="labeled")
    response = post(client, body, signed(body))
    assert response.json()["outcome"] == "ignored"
    assert "workflow_id" not in response.json()
    assert evaluations.started == []


def test_a_signed_body_that_is_not_json_is_rejected() -> None:
    client, _ = client_with(FakeEvaluations())
    body = b"not json"
    assert post(client, body, signed(body)).status_code == 400


def test_a_signed_request_without_delivery_headers_is_rejected() -> None:
    client, _ = client_with(FakeEvaluations())
    body = pull_request()
    headers = signed(body)
    del headers["X-GitHub-Delivery"]
    assert post(client, body, headers).status_code == 400


def test_when_the_evaluation_cannot_start_the_forge_is_told_to_retry() -> None:
    client, journal = client_with(FakeEvaluations(fail=True))
    body = pull_request()
    response = post(client, body, signed(body))
    assert response.status_code == 503
    assert journal.entries == []


def test_health() -> None:
    client, _ = client_with(FakeEvaluations())
    assert client.get("/healthz").json() == {"status": "ok"}


def test_the_root_answers_a_proxy_rather_than_404ing() -> None:
    """A reverse proxy in front of this probes the root and reads 404 as
    nothing being behind the route."""
    client, _ = client_with(FakeEvaluations())
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_a_webhook_secret_is_required() -> None:
    with pytest.raises(ValueError, match="secret"):
        create_app("")


def test_the_instrument_is_given_the_app_once_built() -> None:
    """Another server built on this package traces the ingress's
    requests by passing an instrument; this package passes none."""
    given: list[FastAPI] = []
    app = create_app(SECRET, instrument=given.append)
    assert given == [app]


# --- rotating the secret -----------------------------------------------

OLD_SECRET = "old-secret"


def rotating_client(
    evaluations: FakeEvaluations, previous_secret: str = OLD_SECRET
) -> TestClient:
    use_case = ReceiveDeliveryUseCase(
        QueryableJournal(), FixedClock(), evaluations
    )
    app = create_app(SECRET, receive=use_case, previous_secret=previous_secret)
    return TestClient(app)


def test_while_rotating_the_new_secret_is_accepted_quietly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    evaluations = FakeEvaluations()
    body = pull_request()
    with caplog.at_level(logging.WARNING):
        response = post(rotating_client(evaluations), body, signed(body))
    assert response.status_code == 202
    assert evaluations.started == ["d-1"]
    assert "WEBHOOK_SECRET_PREVIOUS" not in caplog.text


def test_while_rotating_the_previous_secret_is_accepted_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    evaluations = FakeEvaluations()
    body = pull_request()
    headers = signed(body, delivery_id="d-old", secret=OLD_SECRET)
    with caplog.at_level(logging.WARNING):
        response = post(rotating_client(evaluations), body, headers)
    assert response.status_code == 202
    assert evaluations.started == ["d-old"]
    assert "d-old" in caplog.text
    assert "WEBHOOK_SECRET_PREVIOUS" in caplog.text


def test_while_rotating_any_other_secret_is_rejected() -> None:
    evaluations = FakeEvaluations()
    body = pull_request()
    response = post(
        rotating_client(evaluations), body, signed(body, secret="other")
    )
    assert response.status_code == 401
    assert evaluations.started == []


def test_an_empty_previous_secret_accepts_nothing() -> None:
    evaluations = FakeEvaluations()
    body = pull_request()
    client = rotating_client(evaluations, previous_secret="")
    response = post(client, body, signed(body, secret=""))
    assert response.status_code == 401
    assert evaluations.started == []


def test_the_ingress_reads_the_previous_secret_from_the_environment() -> None:
    app = app_from_environment(
        {
            "WEBHOOK_SECRET": SECRET,
            "WEBHOOK_SECRET_PREVIOUS": OLD_SECRET,
            "DATABASE_URL": "postgresql://nowhere/none",
        }
    )
    # Without the lifespan nothing is composed, and a delivery that
    # passed its signature check would fail on the way in; a body that
    # is not JSON is answered 400 before that, and only once its
    # signature passed.
    client = TestClient(app)
    body = b"not json"
    assert (
        post(client, body, signed(body, secret=OLD_SECRET)).status_code == 400
    )
    assert post(client, body, signed(body, secret="other")).status_code == 401


# --- the Forgejo route ----------------------------------------------------

RECORDED = (
    Path(bugflow.forge.tests.__file__).parent / "recorded/forgejo_deliveries"
)
# The webhook secret of the local Forgejo the deliveries were recorded from.
RECORDED_SECRET = "capture-secret"


def forgejo_recording(name: str) -> tuple[bytes, dict[str, str]]:
    """A recorded delivery's raw body and the headers the ingress reads."""
    data = json.loads((RECORDED / f"{name}.json").read_text())
    headers = {
        name: value
        for name, value in data["headers"].items()
        if name.lower().startswith("x-") or name.lower() == "content-type"
    }
    return data["body"].encode(), headers


def forgejo_client(evaluations: FakeEvaluations) -> TestClient:
    use_case = ReceiveDeliveryUseCase(
        QueryableJournal(), FixedClock(), evaluations
    )
    return TestClient(create_app(RECORDED_SECRET, receive=use_case))


@pytest.mark.parametrize(
    ("name", "outcome", "reason"),
    [
        ("01-pull-request-opened", "evaluate", "pull_request opened"),
        (
            "02-pull-request-synchronized",
            "evaluate",
            "pull_request synchronize",
        ),
        ("05-pull-request-comment-created", "dismiss", "dismissal of ED-01"),
        (
            "08-issue-comment-created",
            "ignored",
            "issue_comment is not a dismissal",
        ),
    ],
)
def test_a_recorded_forgejo_delivery_is_received_on_its_route(
    name: str, outcome: str, reason: str
) -> None:
    body, headers = forgejo_recording(name)
    response = forgejo_client(FakeEvaluations()).post(
        "/webhooks/forgejo", content=body, headers=headers
    )
    assert response.status_code == 202
    assert (response.json()["outcome"], response.json()["reason"]) == (
        outcome,
        reason,
    )


def test_the_forgejo_route_checks_forgejos_signature_header() -> None:
    body, headers = forgejo_recording("01-pull-request-opened")
    del headers["X-Forgejo-Signature"]
    response = forgejo_client(FakeEvaluations()).post(
        "/webhooks/forgejo", content=body, headers=headers
    )
    assert response.status_code == 401


# --- the managed agent's completion route ------------------------------

RUN = Correlation(workflow_id="pr/github/o/r/6/evaluation/d-1", run_id="run-1")


class FakeSignal:
    def __init__(self, accepts: bool = True) -> None:
        self.accepts = accepts
        self.signalled: list[tuple[Correlation, str, str]] = []

    def handle_completion(
        self, correlation: Correlation, agent_id: str, remote_id: str
    ) -> Acknowledgement:
        self.signalled.append((correlation, agent_id, remote_id))
        if not self.accepts:
            return Acknowledgement.unable()
        return Acknowledgement.wilco()


def completion_event(
    kind: str = "session.status_idled", session_id: str = "session-1"
) -> bytes:
    return json.dumps(
        {
            "id": "evt_1",
            "created_at": "2026-09-21T00:00:00Z",
            "type": "event",
            "data": {
                "id": session_id,
                "type": kind,
                "organization_id": "org_1",
                "workspace_id": "ws_1",
            },
        }
    ).encode()


def review_signed(
    body: bytes, secret: str = REVIEW_SECRET, msg_id: str = "msg_1"
) -> dict[str, str]:
    # Within the scheme's five-minute tolerance of "now": a fixed date
    # would fail as soon as the clock moved past it.
    timestamp = datetime.now(UTC)
    signature = Webhook(secret).sign(
        msg_id=msg_id, timestamp=timestamp, data=body.decode()
    )
    return {
        "webhook-id": msg_id,
        "webhook-timestamp": str(int(timestamp.timestamp())),
        "webhook-signature": signature,
        "Content-Type": "application/json",
    }


def dispatch_entry(agent_id: str, remote_id: str) -> JournalEntry:
    return JournalEntry(
        event_id=make_event_id(RUN, "agent.dispatched", f"{agent_id}/d"),
        occurred_at=datetime(2026, 9, 21, tzinfo=UTC),
        event_type="agent.dispatched",
        forge="github",
        repo="o/r",
        pr_number=6,
        commit_sha="a" * 40,
        corpus_version=None,
        workflow_id=RUN.workflow_id,
        run_id=RUN.run_id,
        payload={
            "agent_id": agent_id,
            "step": "dispatched",
            "runner": "managed-agent",
            "remote_id": remote_id,
        },
    )


def review_client(
    journal: WorkJournal,
    signal: FakeSignal,
    secret: str = REVIEW_SECRET,
) -> TestClient:
    use_case = ReceiveCompletionUseCase(journal, signal, journal, FixedClock())
    app = create_app(
        SECRET,
        receive=ReceiveDeliveryUseCase(
            QueryableJournal(), FixedClock(), FakeEvaluations()
        ),
        receive_completion=use_case,
        review_webhook_secret=secret,
    )
    return TestClient(app)


def test_a_signed_completion_for_a_known_dispatch_is_signalled() -> None:
    journal = WorkJournal()
    journal.append([dispatch_entry("security", "session-1")])
    signal = FakeSignal()
    client = review_client(journal, signal)
    body = completion_event()
    response = client.post(
        "/webhooks/managed-agent", content=body, headers=review_signed(body)
    )
    assert response.status_code == 202
    assert response.json()["outcome"] == "signalled"
    assert signal.signalled == [(RUN, "security", "session-1")]


def test_a_completion_signed_with_the_wrong_secret_is_rejected() -> None:
    journal = WorkJournal()
    signal = FakeSignal()
    client = review_client(journal, signal)
    body = completion_event()
    response = client.post(
        "/webhooks/managed-agent",
        content=body,
        headers=review_signed(body, secret="whsec_" + "d" * 32),
    )
    assert response.status_code == 401
    assert signal.signalled == []


def test_a_completion_route_with_no_secret_configured_accepts_nothing() -> (
    None
):
    journal = WorkJournal()
    signal = FakeSignal()
    client = review_client(journal, signal, secret="")
    body = completion_event()
    response = client.post(
        "/webhooks/managed-agent", content=body, headers=review_signed(body)
    )
    assert response.status_code == 401


def test_an_event_that_is_not_a_completion_is_ignored() -> None:
    journal = WorkJournal()
    signal = FakeSignal()
    client = review_client(journal, signal)
    body = completion_event(kind="session.status_run_started")
    response = client.post(
        "/webhooks/managed-agent", content=body, headers=review_signed(body)
    )
    assert response.status_code == 202
    assert response.json()["outcome"] == "ignored"
    assert signal.signalled == []


def test_a_signed_body_of_another_shape_is_ignored() -> None:
    journal = WorkJournal()
    signal = FakeSignal()
    client = review_client(journal, signal)
    body = b'["not", "an", "event"]'
    response = client.post(
        "/webhooks/managed-agent", content=body, headers=review_signed(body)
    )
    assert response.status_code == 202
    assert response.json()["outcome"] == "ignored"


def test_a_completion_for_no_recorded_dispatch_is_unknown() -> None:
    journal = WorkJournal()
    signal = FakeSignal()
    client = review_client(journal, signal)
    body = completion_event(session_id="session-never-dispatched")
    response = client.post(
        "/webhooks/managed-agent", content=body, headers=review_signed(body)
    )
    assert response.status_code == 202
    assert response.json()["outcome"] == "unknown"
