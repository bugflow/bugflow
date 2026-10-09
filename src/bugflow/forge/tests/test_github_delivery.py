"""Tests of reading a GitHub webhook delivery."""

from datetime import UTC, datetime

import pytest

from bugflow.forge.domain.models.delivery import DeliveryComment
from bugflow.forge.infrastructure.github_delivery import delivery_from_github
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REPOSITORY = {"name": "one", "owner": {"login": "someone"}}


def test_a_pull_request_delivery_names_its_pull_request() -> None:
    delivery = delivery_from_github(
        {"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "d-1"},
        {"action": "opened", "number": 6, "repository": REPOSITORY},
    )
    assert delivery.delivery_id == "d-1"
    assert (delivery.event, delivery.action) == ("pull_request", "opened")
    assert delivery.repository == "someone/one"
    assert delivery.ref == PullRequestRef(
        owner="someone", repo="one", number=6
    )


def test_a_delivery_says_when_its_pull_request_was_last_updated() -> None:
    """The delivery carries the time GitHub says the pull request last
    changed. That time is what lets the server recognise a polled delivery
    that repeats this one.
    """
    delivery = delivery_from_github(
        {"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "d-1"},
        {
            "action": "synchronize",
            "number": 6,
            "repository": REPOSITORY,
            "pull_request": {"updated_at": "2026-09-19T05:07:04Z"},
        },
    )
    assert delivery.updated_at == datetime(2026, 9, 19, 5, 7, 4, tzinfo=UTC)


def test_header_names_are_case_insensitive() -> None:
    delivery = delivery_from_github(
        {"x-github-event": "pull_request", "x-github-delivery": "d-2"},
        {"action": "edited", "number": 1, "repository": REPOSITORY},
    )
    assert delivery.delivery_id == "d-2"


def test_a_merged_close_carries_the_merge_and_its_commit() -> None:
    delivery = delivery_from_github(
        {"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "d-3"},
        {
            "action": "closed",
            "number": 6,
            "repository": REPOSITORY,
            "pull_request": {"merged": True, "merge_commit_sha": "abc123"},
        },
    )
    assert (delivery.merged, delivery.merge_commit_sha) == (True, "abc123")


def test_a_close_that_abandoned_carries_no_merge() -> None:
    delivery = delivery_from_github(
        {"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "d-4"},
        {
            "action": "closed",
            "number": 6,
            "repository": REPOSITORY,
            "pull_request": {"merged": False, "merge_commit_sha": None},
        },
    )
    assert (delivery.merged, delivery.merge_commit_sha) == (False, None)


def test_other_events_name_no_pull_request() -> None:
    delivery = delivery_from_github(
        {"X-GitHub-Event": "push", "X-GitHub-Delivery": "d-3"},
        {"ref": "refs/heads/master", "repository": REPOSITORY},
    )
    assert delivery.ref is None
    assert delivery.action is None
    assert delivery.repository == "someone/one"


def test_a_request_without_delivery_headers_is_rejected() -> None:
    with pytest.raises(ValueError, match="x-github-delivery"):
        delivery_from_github({"X-GitHub-Event": "push"}, {})


def comment_payload(issue: dict[str, object]) -> dict[str, object]:
    return {
        "action": "created",
        "issue": issue,
        "comment": {
            "id": 99,
            "user": {"login": "reviewer"},
            "body": "/dismiss ED-01 evidence, not narration",
        },
        "repository": REPOSITORY,
    }


def test_a_comment_on_a_pull_request_names_it_and_carries_the_comment() -> (
    None
):
    delivery = delivery_from_github(
        {"X-GitHub-Event": "issue_comment", "X-GitHub-Delivery": "d-4"},
        comment_payload({"number": 6, "pull_request": {"url": "u"}}),
    )
    assert delivery.ref == PullRequestRef(
        owner="someone", repo="one", number=6
    )
    assert delivery.comment == DeliveryComment(
        comment_id=99,
        author="reviewer",
        body="/dismiss ED-01 evidence, not narration",
    )


def test_a_comment_on_an_issue_names_no_pull_request() -> None:
    delivery = delivery_from_github(
        {"X-GitHub-Event": "issue_comment", "X-GitHub-Delivery": "d-5"},
        comment_payload({"number": 7}),
    )
    assert delivery.ref is None
    assert delivery.comment is not None
