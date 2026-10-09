"""Tests of reading a Forgejo webhook delivery.

The deliveries in ``recorded/forgejo_deliveries`` are real ones, recorded
from a Forgejo 16.0.4 running locally with a test user and a test
repository.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from bugflow.forge.domain.models.delivery import Delivery, DeliveryComment
from bugflow.forge.infrastructure.forgejo_delivery import delivery_from_forgejo
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

RECORDED = Path(__file__).parent / "recorded" / "forgejo_deliveries"
REF = PullRequestRef(forge="forgejo", owner="probe", repo="hooks", number=1)


def recorded(name: str) -> tuple[dict[str, str], dict[str, Any]]:
    data = json.loads((RECORDED / f"{name}.json").read_text())
    return data["headers"], json.loads(data["body"])


def normalised(name: str) -> Delivery:
    return delivery_from_forgejo(*recorded(name))


def test_an_opened_pull_request_is_named_on_forgejo() -> None:
    delivery = normalised("01-pull-request-opened")
    assert (delivery.forge, delivery.event, delivery.action) == (
        "forgejo",
        "pull_request",
        "opened",
    )
    assert delivery.ref == REF
    assert delivery.repository == "probe/hooks"
    assert delivery.delivery_id == "24df010e-efa7-4176-a6ad-9c75b694d132"


@pytest.mark.parametrize(
    ("name", "action"),
    [
        ("02-pull-request-synchronized", "synchronize"),
        ("03-pull-request-title-edited", "edited"),
        ("09-pull-request-closed", "closed"),
    ],
)
def test_pull_request_actions_take_the_domains_names(
    name: str, action: str
) -> None:
    delivery = normalised(name)
    assert (delivery.action, delivery.ref) == (action, REF)


def test_a_comment_on_a_pull_request_names_it_and_carries_the_comment() -> (
    None
):
    delivery = normalised("05-pull-request-comment-created")
    assert (delivery.event, delivery.action, delivery.ref) == (
        "issue_comment",
        "created",
        REF,
    )
    assert delivery.comment == DeliveryComment(
        comment_id=21,
        author="probe",
        body="/dismiss ED-01 evidence, not narration",
    )


def test_a_close_that_abandoned_carries_no_merge() -> None:
    delivery = normalised("09-pull-request-closed")
    assert (delivery.merged, delivery.merge_commit_sha) == (False, None)


def test_a_comment_on_a_plain_issue_names_no_pull_request() -> None:
    headers, body = recorded("08-issue-comment-created")
    assert "pull_request" in body["issue"]
    delivery = delivery_from_forgejo(headers, body)
    assert delivery.ref is None
    assert delivery.comment is not None


def test_an_issue_event_names_no_pull_request() -> None:
    assert normalised("07-issue-opened").ref is None


def test_a_request_without_forgejo_delivery_headers_is_rejected() -> None:
    with pytest.raises(ValueError, match="x-forgejo-delivery"):
        delivery_from_forgejo({"X-Forgejo-Event": "push"}, {})
