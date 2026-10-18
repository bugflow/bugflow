"""Contribution checks use retained commit emails within one pull request."""

from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa

from bugflow.forge.domain.models.pull_request import (
    Authorship,
    CommitSnapshot,
    PullRequestSnapshot,
)
from bugflow.forge.infrastructure.in_memory_snapshots import (
    InMemorySnapshotStore,
)
from bugflow.forge.infrastructure.sqlalchemy_snapshots import (
    SqlAlchemySnapshotStore,
    snapshots,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

Store = InMemorySnapshotStore | SqlAlchemySnapshotStore
EMAIL = "Contributor@example.com"


@pytest.fixture(params=["memory", "postgres"])
def store(request: pytest.FixtureRequest) -> Store:
    if request.param == "memory":
        return InMemorySnapshotStore()
    request.getfixturevalue("engine")
    return SqlAlchemySnapshotStore(request.getfixturevalue("database_url"))


@pytest.fixture
def ref() -> PullRequestRef:
    return PullRequestRef(owner="org", repo=f"repo-{uuid4().hex}", number=1)


def snapshot(
    ref: PullRequestRef, *, author: str = "", committer: str = ""
) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        ref=ref,
        title="A change",
        body="Private submission content",
        head_branch="change",
        base_branch="main",
        commits=(
            CommitSnapshot(
                sha="head",
                message="A commit",
                author=Authorship(email=author),
                committer=Authorship(email=committer),
            ),
        ),
        files=(),
    )


@pytest.mark.parametrize("role", ["author", "committer"])
def test_author_or_committer_email_grants_a_contribution(
    store: Store, ref: PullRequestRef, role: str
) -> None:
    store.put(snapshot(ref, **{role: EMAIL}))
    assert store.has_contribution(
        ref, frozenset({"another@example.com", EMAIL})
    )


def test_a_commit_in_an_older_retained_snapshot_still_counts(
    store: Store, ref: PullRequestRef
) -> None:
    earlier = snapshot(ref, author=EMAIL)
    store.put(
        replace(
            earlier,
            commits=(
                CommitSnapshot(sha="first", message="Another person's commit"),
                *earlier.commits,
            ),
        )
    )
    store.put(snapshot(ref, author="replacement@example.com"))
    assert store.has_contribution(ref, frozenset({EMAIL}))


@pytest.mark.parametrize("part", ["forge", "owner", "repo", "number"])
def test_a_contribution_in_another_pull_request_does_not_count(
    store: Store, ref: PullRequestRef, part: str
) -> None:
    foreign = {
        "forge": replace(ref, forge="forgejo"),
        "owner": replace(ref, owner="elsewhere"),
        "repo": replace(ref, repo="another"),
        "number": replace(ref, number=2),
    }[part]
    store.put(snapshot(foreign, author=EMAIL))
    assert not store.has_contribution(ref, frozenset({EMAIL}))


@pytest.mark.parametrize(
    "alias",
    [
        "contributor@example.com",
        "Contributor@EXAMPLE.COM",
        " Contributor@example.com",
        "Contributor@example.com ",
    ],
)
def test_email_matching_is_exact(
    store: Store, ref: PullRequestRef, alias: str
) -> None:
    store.put(snapshot(ref, author=EMAIL))
    assert not store.has_contribution(ref, frozenset({alias}))


def test_missing_snapshots_aliases_and_commit_emails_deny(
    store: Store, ref: PullRequestRef
) -> None:
    assert not store.has_contribution(ref, frozenset({EMAIL}))
    store.put(snapshot(ref))
    assert not store.has_contribution(ref, frozenset({EMAIL}))
    assert not store.has_contribution(ref, frozenset({"", "  "}))
    store.put(snapshot(ref, author=EMAIL))
    assert not store.has_contribution(ref, frozenset())


def test_names_logins_and_pull_request_authorship_do_not_grant_access(
    store: Store, ref: PullRequestRef
) -> None:
    value = snapshot(ref)
    named = Authorship(name=EMAIL, login=EMAIL)
    commit = replace(value.commits[0], author=named, committer=named)
    store.put(replace(value, author_login=EMAIL, commits=(commit,)))
    assert not store.has_contribution(ref, frozenset({EMAIL}))


def test_deleting_the_only_contributing_snapshot_removes_the_evidence(
    store: Store, ref: PullRequestRef
) -> None:
    identity = store.put(snapshot(ref, author=EMAIL)).snapshot_id
    assert store.has_contribution(ref, frozenset({EMAIL}))
    if isinstance(store, InMemorySnapshotStore):
        del store.snapshots[identity]
    else:
        with store._engine.begin() as connection:
            connection.execute(
                sa.delete(snapshots).where(snapshots.c.snapshot_id == identity)
            )
    assert not store.has_contribution(ref, frozenset({EMAIL}))


def test_postgres_transfers_only_the_boolean_and_skips_empty_aliases(
    database_url: str, engine: sa.Engine, ref: PullRequestRef
) -> None:
    store = SqlAlchemySnapshotStore(database_url)
    store.put(snapshot(ref, author=EMAIL))
    shapes: list[tuple[int, ...]] = []

    def record(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        shapes.append(tuple(column.type_code for column in cursor.description))

    sa.event.listen(store._engine, "after_cursor_execute", record)
    try:
        assert not store.has_contribution(ref, frozenset())
        assert shapes == []
        assert store.has_contribution(ref, frozenset({EMAIL}))
    finally:
        sa.event.remove(store._engine, "after_cursor_execute", record)
    # PostgreSQL's boolean type has object identifier 16.
    assert shapes == [(16,)]
