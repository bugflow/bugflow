"""New snapshot provenance is retained without changing historical hashes."""

import hashlib
import json
from dataclasses import asdict, replace
from typing import Any
from uuid import uuid4

import httpx2
import pytest
import sqlalchemy as sa

from bugflow.forge.domain.errors import (
    ForgeRejectedError,
    SnapshotNotFoundError,
)
from bugflow.forge.domain.models.pull_request import (
    Authorship,
    CommitSnapshot,
    PullRequestSnapshot,
)
from bugflow.forge.infrastructure.forgejo import ForgejoForge
from bugflow.forge.infrastructure.github import GitHubForge
from bugflow.forge.infrastructure.in_memory_snapshots import (
    InMemorySnapshotStore,
)
from bugflow.forge.infrastructure.sqlalchemy_snapshots import (
    SqlAlchemySnapshotStore,
    snapshots,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.domain.values.repository_association import (
    AssociationConflictError,
    RepositoryAssociation,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin
from bugflow.shared.infrastructure.in_memory_repository_associations import (
    InMemoryRepositoryAssociations,
)
from bugflow.shared.infrastructure.serde import from_json
from bugflow.shared.infrastructure.sqlalchemy_repository_associations import (
    SqlAlchemyRepositoryAssociations,
)

REF = PullRequestRef(owner="o", repo="r", number=1)
PULL = {
    "title": "Change",
    "body": "",
    "head": {"ref": "topic"},
    "base": {"ref": "main"},
}


def snapshot() -> PullRequestSnapshot:
    return PullRequestSnapshot(
        ref=REF,
        title=str(uuid4()),
        body="retained evidence",
        head_branch="topic",
        base_branch="main",
        files=(),
        commits=(
            CommitSnapshot(
                sha="abc",
                message="Change",
                author=Authorship(email="author@example.test"),
            ),
        ),
    )


def test_historical_body_decodes_with_its_original_content_hash() -> None:
    body = asdict(snapshot())
    body.pop("origin")
    old_id = hashlib.sha256(
        json.dumps(body, separators=(",", ":")).encode()
    ).hexdigest()
    decoded = from_json(PullRequestSnapshot, body)
    assert decoded.origin is None
    assert decoded.content_id == old_id
    assert (
        from_json(PullRequestSnapshot, body | {"origin": None}).content_id
        == old_id
    )


@pytest.mark.parametrize(
    "origin", ["https://one.test/o/r", "one.test/other/r"]
)
def test_snapshot_refuses_noncanonical_or_mismatching_origin(
    origin: str,
) -> None:
    with pytest.raises(ValueError):
        replace(snapshot(), origin=origin)


@pytest.fixture(params=["memory", "postgres"])
def stores(request: pytest.FixtureRequest) -> Any:
    if request.param == "memory":
        associations = InMemoryRepositoryAssociations()
        return InMemorySnapshotStore(associations), associations
    request.getfixturevalue("engine")
    url = request.getfixturevalue("database_url")
    return SqlAlchemySnapshotStore(url), SqlAlchemyRepositoryAssociations(url)


def test_new_snapshots_are_readable_only_at_their_origin(stores: Any) -> None:
    store, associations = stores
    old = snapshot()
    one = replace(old, origin="one.test/o/r")
    two = replace(old, origin="two.test/o/r")
    assert len({old.content_id, one.content_id, two.content_id}) == 3
    old_ref = store.put(old)
    reference = store.put(one)
    assert store.put(one) == reference
    assert associations.origin_for("snapshot", old_ref.snapshot_id) is None
    assert (
        str(associations.origin_for("snapshot", reference.snapshot_id))
        == one.origin
    )
    assert store.get(reference) == one  # Existing internal workflow handles.
    canonical = replace(reference, origin=one.origin)
    assert store.get_bounded(canonical, 100_000)[0] == one
    with pytest.raises(SnapshotNotFoundError):
        store.get_bounded(replace(reference, origin=two.origin), 100_000)
    emails = frozenset({"author@example.test"})
    assert store.has_contribution(REF, emails, origin=one.origin)
    assert not store.has_contribution(REF, emails, origin=two.origin)
    other = store.put(two)
    assert other.snapshot_id != reference.snapshot_id
    assert (
        store.get_bounded(replace(other, origin=two.origin), 100_000)[0] == two
    )


def test_conflicting_association_does_not_leave_a_snapshot(
    stores: Any,
) -> None:
    store, associations = stores
    new = replace(snapshot(), origin="one.test/o/r")
    associations.associate(
        (
            RepositoryAssociation(
                kind="snapshot",
                record_id=new.content_id,
                origin=RepositoryOrigin("two.test/o/r"),
            ),
        )
    )
    with pytest.raises(AssociationConflictError):
        store.put(new)
    if isinstance(store, InMemorySnapshotStore):
        assert new.content_id not in store.snapshots
    else:
        with store._engine.connect() as connection:
            assert (
                connection.execute(
                    sa.select(snapshots.c.snapshot_id).where(
                        snapshots.c.snapshot_id == new.content_id
                    )
                ).first()
                is None
            )


def handler(request: httpx2.Request) -> httpx2.Response:
    path = request.url.path
    if path.endswith("/pulls/1"):
        return httpx2.Response(200, json=PULL)
    if path.endswith("/commits"):
        return httpx2.Response(
            200, json=[{"sha": "abc", "commit": {"message": "Change"}}]
        )
    if path.endswith("/commits/abc"):
        return httpx2.Response(200, json={"files": []})
    if path.endswith(".diff"):
        return httpx2.Response(200, text="")
    return httpx2.Response(200, json=[])


@pytest.mark.parametrize(
    "url,expected",
    [
        (None, "github.com/o/r"),
        ("https://ONE.test:8443", "one.test:8443/o/r"),
        ("https://two.test:443", "two.test/o/r"),
        ("http://local.test", None),
    ],
)
def test_adapter_uses_its_endpoint_for_snapshot_provenance(
    url: str | None, expected: str | None
) -> None:
    transport = httpx2.MockTransport(handler)
    forge = (
        GitHubForge("t", transport=transport)
        if url is None
        else ForgejoForge(url, "t", transport=transport)
    )
    observed = forge.fetch_snapshot(REF)
    assert observed.origin == expected
    store = InMemorySnapshotStore()
    reference = store.put(observed)
    assert (
        store.get_bounded(replace(reference, origin=expected), 100_000)[0]
        == observed
    )


@pytest.mark.parametrize("kind", ["github", "forgejo"])
@pytest.mark.parametrize(
    "part",
    [
        "/pulls/1",
        "/pulls/1/commits",
        "/pulls/1/files",
        "/commits/abc",
        "/pulls/1.diff",
    ],
)
@pytest.mark.parametrize(
    "location",
    ["https://other.test/o/r", "https://api.github.com/repos/o/renamed"],
)
def test_snapshot_reads_never_follow_redirects(
    kind: str, part: str, location: str
) -> None:
    if (kind == "github" and part.endswith(".diff")) or (
        kind == "forgejo" and part == "/commits/abc"
    ):
        pytest.skip("endpoint belongs to the other adapter")
    seen: list[str] = []

    def redirect(request: httpx2.Request) -> httpx2.Response:
        seen.append(str(request.url))
        if request.url.path.endswith(part):
            return httpx2.Response(301, headers={"Location": location})
        return handler(request)

    transport = httpx2.MockTransport(redirect)
    forge = (
        GitHubForge("t", transport=transport)
        if kind == "github"
        else ForgejoForge("https://one.test", "t", transport=transport)
    )
    with pytest.raises(ForgeRejectedError):
        forge.fetch_snapshot(REF)
    assert not any(url.startswith(location) for url in seen)


def test_unsupported_https_endpoint_is_refused_before_a_request() -> None:
    seen: list[str] = []

    def called(request: httpx2.Request) -> httpx2.Response:
        seen.append(str(request.url))
        return handler(request)

    forge = ForgejoForge(
        "https://one.test/subpath", "t", transport=httpx2.MockTransport(called)
    )
    with pytest.raises(ForgeRejectedError, match="canonical repository"):
        forge.fetch_snapshot(REF)
    assert seen == []


def test_legacy_body_and_hash_survive_mapping_and_reinsertion(
    database_url: str, engine: sa.Engine
) -> None:
    store = SqlAlchemySnapshotStore(database_url)
    old = snapshot()
    reference = store.put(old)
    query = sa.select(snapshots.c.body).where(
        snapshots.c.snapshot_id == reference.snapshot_id
    )
    with engine.connect() as connection:
        before = connection.execute(query).scalar_one()
    assert "origin" not in before
    associations = SqlAlchemyRepositoryAssociations(database_url)
    associations.associate(
        (
            RepositoryAssociation(
                kind="snapshot",
                record_id=reference.snapshot_id,
                origin=RepositoryOrigin("one.test/o/r"),
            ),
        )
    )
    assert store.put(store.get(reference)) == reference
    with engine.connect() as connection:
        assert connection.execute(query).scalar_one() == before
    assert (
        store.get_bounded(replace(reference, origin="one.test/o/r"), 100_000)[
            0
        ].content_id
        == reference.snapshot_id
    )
    associations.close()
