"""Tests of the poller's sender.

Each delivery it posts is checked with the same signature check and read
with the same parser that a real delivery goes through. If the sender and
the receiving side ever disagree about the format, these tests fail.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime

import httpx2
import pytest

from bugflow.forge.domain.errors import DeliveryNotAcceptedError
from bugflow.forge.domain.models.delivery import Delivery, DeliveryComment
from bugflow.forge.infrastructure.forgejo_delivery import delivery_from_forgejo
from bugflow.forge.infrastructure.github_delivery import delivery_from_github
from bugflow.forge.infrastructure.signatures import (
    FORGEJO_SIGNATURE_HEADER,
    GITHUB_SIGNATURE_HEADER,
    forgejo_signature_valid,
    github_signature_valid,
)
from bugflow.forge.infrastructure.webhook_sink import SignedWebhookSink
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

SECRET = "test-secret"
URL = "http://server.example:8000"
DELIVERY = Delivery(
    forge="github",
    delivery_id="poll-0123",
    event="pull_request",
    action="synchronize",
    repository="o/r",
    ref=PullRequestRef(owner="o", repo="r", number=7),
    updated_at=datetime(2026, 9, 19, 5, 7, 4, tzinfo=UTC),
)


def sink(
    status: int = 202,
    outcome: str = "evaluate",
    seen: list[httpx2.Request] | None = None,
) -> SignedWebhookSink:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if seen is not None:
            seen.append(request)
        return httpx2.Response(status, json={"outcome": outcome})

    return SignedWebhookSink(URL, SECRET, httpx2.MockTransport(handler))


def test_a_posted_delivery_is_one_the_server_accepts() -> None:
    seen: list[httpx2.Request] = []
    assert sink(seen=seen).send(DELIVERY) == "evaluate"
    (request,) = seen
    assert str(request.url) == f"{URL}/webhooks/github"
    body = request.content
    assert github_signature_valid(
        SECRET, body, request.headers[GITHUB_SIGNATURE_HEADER]
    )
    assert delivery_from_github(request.headers, json.loads(body)) == DELIVERY


def test_a_delivery_the_server_refuses_is_not_accepted() -> None:
    with pytest.raises(DeliveryNotAcceptedError, match="401"):
        sink(status=401).send(DELIVERY)


def test_an_unreachable_server_is_not_accepted() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    unreachable = SignedWebhookSink(URL, SECRET, httpx2.MockTransport(handler))
    with pytest.raises(DeliveryNotAcceptedError, match="could not reach"):
        unreachable.send(DELIVERY)


def test_a_sink_needs_a_secret() -> None:
    with pytest.raises(ValueError, match="secret"):
        SignedWebhookSink(URL, "")


COMMENT = Delivery(
    forge="github",
    delivery_id="poll-comment",
    event="issue_comment",
    action="created",
    repository="o/r",
    ref=PullRequestRef(owner="o", repo="r", number=7),
    comment=DeliveryComment(
        comment_id=99, author="reviewer", body="/dismiss ED-01 evidence"
    ),
)


def test_a_posted_comment_is_one_the_server_reads_back() -> None:
    seen: list[httpx2.Request] = []
    assert sink(outcome="dismiss", seen=seen).send(COMMENT) == "dismiss"
    (request,) = seen
    body = request.content
    assert github_signature_valid(
        SECRET, body, request.headers[GITHUB_SIGNATURE_HEADER]
    )
    assert delivery_from_github(request.headers, json.loads(body)) == COMMENT


ON_FORGEJO = PullRequestRef(forge="forgejo", owner="o", repo="r", number=7)


@pytest.mark.parametrize(
    "delivery",
    [
        replace(DELIVERY, forge="forgejo", ref=ON_FORGEJO),
        replace(COMMENT, forge="forgejo", ref=ON_FORGEJO),
    ],
)
def test_a_forgejo_delivery_is_one_forgejos_route_reads_back(
    delivery: Delivery,
) -> None:
    seen: list[httpx2.Request] = []
    sink(seen=seen).send(delivery)
    (request,) = seen
    assert str(request.url) == f"{URL}/webhooks/forgejo"
    body = request.content
    header = request.headers[FORGEJO_SIGNATURE_HEADER]
    assert forgejo_signature_valid(SECRET, body, header)
    assert delivery_from_forgejo(request.headers, json.loads(body)) == delivery


def test_a_forgejo_push_is_posted_as_forgejo_names_it() -> None:
    seen: list[httpx2.Request] = []
    delivery = replace(DELIVERY, forge="forgejo", ref=ON_FORGEJO)
    sink(seen=seen).send(delivery)
    assert json.loads(seen[0].content)["action"] == "synchronized"
