"""Tests of the small rules in the forge context's domain."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from bugflow.forge.domain import facts
from bugflow.forge.domain.models.delivery import forge_time
from bugflow.forge.domain.models.pull_request import (
    ChangedFile,
    CommitSnapshot,
    PullRequestSnapshot,
)
from bugflow.forge.domain.models.webhook import Webhook
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="someone", repo="one", number=8)


def snapshot(title: str = "A title") -> PullRequestSnapshot:
    return PullRequestSnapshot(
        ref=REF,
        title=title,
        body="",
        head_branch="a-branch",
        base_branch="master",
        base_sha="b" * 40,
        commits=(
            CommitSnapshot(sha="1" * 40, message="First\n\nBody."),
            CommitSnapshot(sha="2" * 40, message="Second"),
        ),
        files=(
            ChangedFile(path="a.py", additions=3, deletions=1, patch="@@"),
            ChangedFile(path="b.bin", additions=0, deletions=2, patch=None),
        ),
    )


@pytest.mark.parametrize(
    ("text", "forge"),
    [
        ("someone/one", "github"),
        ("forgejo:someone/one", "forgejo"),
        ("github:someone/one", "github"),
        ("  someone/one\n", "github"),
    ],
)
def test_a_watched_repository_is_read_with_its_forge(
    text: str, forge: str
) -> None:
    assert WatchedRepository.parse(text) == WatchedRepository(
        forge=forge,  # type: ignore[arg-type]
        owner="someone",
        repo="one",
    )


def test_a_watched_repository_is_written_as_it_is_read() -> None:
    for text in ("someone/one", "forgejo:someone/one"):
        assert str(WatchedRepository.parse(text)) == text


@pytest.mark.parametrize("text", ["someone", "gitlab:someone/one", "a/b/c"])
def test_text_that_names_no_repository_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="not owner/repo"):
        WatchedRepository.parse(text)


def test_a_webhook_matches_only_the_same_url_and_events_when_active() -> None:
    events = frozenset({"pull_request", "issue_comment"})
    hook = Webhook(
        hook_id=1, url="https://x.example/hook", events=events, active=True
    )

    assert hook.matches("https://x.example/hook", events)
    assert not hook.matches("https://x.example/hook/", events)
    assert not hook.matches("https://x.example/hook", frozenset({"push"}))
    assert not Webhook(
        hook_id=1, url="https://x.example/hook", events=events, active=False
    ).matches("https://x.example/hook", events)


def test_a_forge_s_timestamp_is_read_with_z_or_an_offset() -> None:
    assert forge_time("2026-09-21T01:56:45Z") == datetime(
        2026, 9, 21, 1, 56, 45, tzinfo=UTC
    )
    assert forge_time("2026-09-21T11:56:45+10:00") == datetime(
        2026, 9, 21, 11, 56, 45, tzinfo=timezone(timedelta(hours=10))
    )
    assert forge_time("") is None
    assert forge_time(None) is None


def test_a_snapshot_is_summarised() -> None:
    summary = snapshot().summary()

    assert (summary.commit_count, summary.file_count) == (2, 2)
    assert summary.changed_lines == 6
    assert summary.head_sha == "2" * 40
    assert summary.base_sha == "b" * 40
    assert snapshot().commits[0].summary == "First"


def test_a_snapshot_s_id_changes_only_when_its_content_does() -> None:
    assert snapshot().content_id == snapshot().content_id
    assert snapshot().content_id != snapshot("Another title").content_id


def test_a_delivery_s_fact_has_one_id_whichever_run_handles_it() -> None:
    """Pins one id. A journal keeps one entry for each id, so if the way
    this id is made changed, a delivery the forge sent again would be
    recorded a second time."""
    assert facts.delivery_id("github", "a-delivery") == UUID(
        "5c9195af-2c61-55c1-a7a0-5e2029770781"
    )
    assert facts.delivery_id("github", "a-delivery") != facts.delivery_id(
        "forgejo", "a-delivery"
    )
