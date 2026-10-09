"""Tests of managing webhooks, run against every adapter that can.

Only the GitHub adapter can today. The tests take the adapter as a
parameter all the same, so that adding a second forge means adding a fake
and not rewriting the tests.

They are separate from ``test_forge_conformance.py`` because not every
forge adapter manages webhooks.
"""

import json
from collections.abc import Iterator

import httpx2
import pytest

from bugflow.forge.domain.errors import ForgeRejectedError
from bugflow.forge.domain.repositories.webhook_admin import (
    WebhookAdminRepository,
)
from bugflow.forge.infrastructure.github import GitHubForge

# The fake of GitHub is imported from the other conformance tests, so that
# there is only one fake of GitHub to keep correct.
from bugflow.forge.tests.test_forge_conformance import FakeGitHub
from bugflow.shared.infrastructure.serde import to_json

OWNER, REPO = "o", "r"
URL = "https://server.invalid/webhooks/github"
EVENTS = frozenset({"pull_request", "issue_comment"})


@pytest.fixture(params=["github"])
def subject(
    request: pytest.FixtureRequest,
) -> Iterator[tuple[WebhookAdminRepository, FakeGitHub]]:
    backend = FakeGitHub()
    forge = GitHubForge(
        "token", transport=httpx2.MockTransport(backend.handle)
    )
    yield forge, backend


def test_a_repository_with_no_hooks_lists_none(
    subject: tuple[WebhookAdminRepository, FakeGitHub],
) -> None:
    forge, _ = subject
    assert forge.list_hooks(OWNER, REPO) == []


def test_a_created_hook_is_listed_with_what_it_was_given(
    subject: tuple[WebhookAdminRepository, FakeGitHub],
) -> None:
    forge, _ = subject
    created = forge.create_hook(OWNER, REPO, URL, "s3cret", EVENTS)
    assert (created.url, created.events, created.active) == (URL, EVENTS, True)
    assert forge.list_hooks(OWNER, REPO) == [created]


def test_the_secret_is_sent_and_never_returned(
    subject: tuple[WebhookAdminRepository, FakeGitHub],
) -> None:
    """The secret is sent to the forge and is not in anything the forge
    returns. Because it cannot be read back, it is written on every update.
    """
    forge, backend = subject
    forge.create_hook(OWNER, REPO, URL, "s3cret", EVENTS)
    stored = backend.hooks[(OWNER, REPO)][0]
    assert stored["config"]["secret"] == "s3cret"
    listed = forge.list_hooks(OWNER, REPO)[0]
    assert "s3cret" not in json.dumps(to_json(listed))


def test_a_hook_posts_json_so_the_signature_covers_the_body(
    subject: tuple[WebhookAdminRepository, FakeGitHub],
) -> None:
    """A webhook is created to post JSON. With form encoding the JSON would
    arrive inside a form field, and the receiving side could neither read
    it nor check its signature.
    """
    forge, backend = subject
    forge.create_hook(OWNER, REPO, URL, "s3cret", EVENTS)
    assert backend.hooks[(OWNER, REPO)][0]["config"]["content_type"] == "json"


def test_updating_a_hook_changes_it_in_place(
    subject: tuple[WebhookAdminRepository, FakeGitHub],
) -> None:
    forge, _ = subject
    created = forge.create_hook(OWNER, REPO, URL, "old", frozenset({"push"}))
    updated = forge.update_hook(
        OWNER, REPO, created.hook_id, URL, "new", EVENTS
    )
    assert updated.hook_id == created.hook_id
    assert updated.events == EVENTS
    assert forge.list_hooks(OWNER, REPO) == [updated]


def test_a_deleted_hook_is_gone(
    subject: tuple[WebhookAdminRepository, FakeGitHub],
) -> None:
    forge, _ = subject
    created = forge.create_hook(OWNER, REPO, URL, "s3cret", EVENTS)
    forge.delete_hook(OWNER, REPO, created.hook_id)
    assert forge.list_hooks(OWNER, REPO) == []


def test_deleting_a_hook_that_is_already_gone_is_not_an_error(
    subject: tuple[WebhookAdminRepository, FakeGitHub],
) -> None:
    """Deleting a webhook that is already gone succeeds. Two runs at once, or
    one run retried, must not fail on the second delete.
    """
    forge, _ = subject
    created = forge.create_hook(OWNER, REPO, URL, "s3cret", EVENTS)
    forge.delete_hook(OWNER, REPO, created.hook_id)
    forge.delete_hook(OWNER, REPO, created.hook_id)


def test_updating_a_hook_that_does_not_exist_is_rejected(
    subject: tuple[WebhookAdminRepository, FakeGitHub],
) -> None:
    forge, _ = subject
    with pytest.raises(ForgeRejectedError):
        forge.update_hook(OWNER, REPO, 404, URL, "s3cret", EVENTS)


def test_hooks_are_kept_per_repository(
    subject: tuple[WebhookAdminRepository, FakeGitHub],
) -> None:
    """A webhook on one repository is not listed for another."""
    forge, _ = subject
    forge.create_hook(OWNER, REPO, URL, "s3cret", EVENTS)
    assert forge.list_hooks(OWNER, "elsewhere") == []
