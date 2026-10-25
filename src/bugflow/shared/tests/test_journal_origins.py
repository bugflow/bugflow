"""Run provenance applies to new events without rewriting retained facts."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
import sqlalchemy as sa

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.models.recorder import Recorder
from bugflow.shared.domain.repositories.repository_associations import (
    RepositoryAssociations,
)
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.domain.values.repository_association import (
    AssociationConflictError,
    RepositoryAssociation,
    RepositoryAssociationUnresolvedError,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal
from bugflow.shared.infrastructure.in_memory_repository_associations import (
    InMemoryRepositoryAssociations,
)
from bugflow.shared.infrastructure.sqlalchemy_journal import (
    SqlAlchemyJournal,
    journal,
)
from bugflow.shared.infrastructure.sqlalchemy_repository_associations import (
    SqlAlchemyRepositoryAssociations,
)

REF = PullRequestRef(forge="forgejo", owner="team", repo="project", number=7)
ONE = "one.example/team/project"
TWO = "two.example/team/project"
NOW = datetime(2026, 10, 19, tzinfo=UTC)
Store = InMemoryJournal | SqlAlchemyJournal


@pytest.fixture(params=["memory", "postgres"])
def stores(
    request: pytest.FixtureRequest,
) -> Iterator[tuple[Store, RepositoryAssociations]]:
    if request.param == "memory":
        associations = InMemoryRepositoryAssociations()
        yield InMemoryJournal(associations=associations), associations
    else:
        request.getfixturevalue("engine")
        url = request.getfixturevalue("database_url")
        postgres = SqlAlchemyRepositoryAssociations(url)
        writer = SqlAlchemyJournal(url)
        try:
            yield writer, postgres
        finally:
            postgres.close()
            writer._engine.dispose()


def recorder(origin: str | None = None) -> Recorder:
    return Recorder(
        REF,
        Correlation(workflow_id=str(uuid4()), run_id="run"),
        "v1",
        NOW,
        origin=origin,
    )


def next_event(
    entry: JournalEntry, key: str = "judge.invoked"
) -> JournalEntry:
    return replace(entry, event_id=uuid4(), event_type=key, origin=None)


def test_observation_origin_applies_to_later_records_and_retries(
    stores: tuple[Store, RepositoryAssociations],
) -> None:
    writer, associations = stores
    observed = recorder(ONE).entry(
        "pr.observed", "head", {"snapshot_id": "snapshot"}
    )
    writer.append([observed])
    writer.append([observed])
    subsequent = [
        next_event(observed, event_type)
        for event_type in (
            "llm.called",
            "judge.invoked",
            "finding.raised",
            "action.taken",
        )
    ]
    writer.append(subsequent)
    for entry in (observed, *subsequent):
        assert (
            str(associations.origin_for("journal", str(entry.event_id))) == ONE
        )
    # An existing event's row survives a retry, a legacy one included.
    writer.append([replace(observed, origin=None, commit_sha="changed")])
    if isinstance(writer, InMemoryJournal):
        held = next(
            entry
            for entry in writer.entries
            if entry.event_id == observed.event_id
        )
        assert held.commit_sha == observed.commit_sha
        assert held.origin is None
    else:
        with writer._engine.connect() as connection:
            assert (
                connection.execute(
                    sa.select(journal.c.commit_sha).where(
                        journal.c.event_id == observed.event_id
                    )
                ).scalar_one()
                == observed.commit_sha
            )


def test_same_run_cannot_change_hosts(
    stores: tuple[Store, RepositoryAssociations],
) -> None:
    writer, associations = stores
    observed = recorder(ONE).entry("pr.observed", "head", {})
    writer.append([observed])
    changed = replace(next_event(observed), origin=TWO)
    with pytest.raises(AssociationConflictError):
        writer.append([changed])
    assert not writer.has_event(changed.event_id)
    assert (
        str(associations.origin_for("journal", str(observed.event_id))) == ONE
    )
    with pytest.raises(AssociationConflictError):
        writer.append([replace(observed, origin=TWO)])


@pytest.mark.parametrize(
    "field,value",
    [
        ("workflow_id", "elsewhere"),
        ("run_id", "another"),
        ("forge", "github"),
        ("repo", "team/other"),
        ("pr_number", 8),
    ],
)
def test_inheritance_does_not_cross_scope(
    stores: tuple[Store, RepositoryAssociations], field: str, value: str | int
) -> None:
    writer, associations = stores
    observed = recorder(ONE).entry("pr.observed", "head", {})
    writer.append([observed])
    other = replace(next_event(observed), **{field: value})  # type: ignore[arg-type]
    writer.append([other])
    assert associations.origin_for("journal", str(other.event_id)) is None


def test_a_new_run_can_use_a_different_host(
    stores: tuple[Store, RepositoryAssociations],
) -> None:
    writer, associations = stores
    one = recorder(ONE).entry("pr.observed", "head", {})
    two = replace(next_event(one), run_id="new-run", origin=TWO)
    writer.append([one, two])
    assert str(associations.origin_for("journal", str(one.event_id))) == ONE
    assert str(associations.origin_for("journal", str(two.event_id))) == TWO


def test_canonical_retry_does_not_assign_an_unresolved_event(
    stores: tuple[Store, RepositoryAssociations],
) -> None:
    writer, associations = stores
    old = recorder().entry("pr.observed", "head", {})
    writer.append([old])
    with pytest.raises(RepositoryAssociationUnresolvedError):
        writer.append([replace(old, origin=ONE)])
    fresh = replace(next_event(old), origin=ONE)
    with pytest.raises(RepositoryAssociationUnresolvedError):
        writer.append([fresh])
    assert not writer.has_event(fresh.event_id)
    assert associations.origin_for("journal", str(old.event_id)) is None


def test_duplicate_id_from_another_scope_cannot_acquire_origin(
    stores: tuple[Store, RepositoryAssociations],
) -> None:
    writer, associations = stores
    old = recorder().entry("pr.observed", "head", {})
    writer.append([old])
    with pytest.raises(AssociationConflictError):
        writer.append([replace(old, run_id="another", origin=ONE)])
    assert associations.origin_for("journal", str(old.event_id)) is None


def test_conflicting_batch_rolls_back_all_events_and_associations(
    stores: tuple[Store, RepositoryAssociations],
) -> None:
    writer, associations = stores
    bad = recorder(ONE).entry("pr.observed", "head", {})
    good = recorder(ONE).entry("pr.observed", "head", {})
    associations.associate(
        (
            RepositoryAssociation(
                kind="journal",
                record_id=str(bad.event_id),
                origin=RepositoryOrigin(TWO),
            ),
        )
    )
    with pytest.raises(AssociationConflictError):
        writer.append([good, bad])
    for entry in (good, bad):
        assert not writer.has_event(entry.event_id)
    assert associations.origin_for("journal", str(good.event_id)) is None


def test_mixed_historical_mappings_do_not_establish_provenance(
    stores: tuple[Store, RepositoryAssociations],
) -> None:
    writer, associations = stores
    old = recorder().entry("pr.observed", "head", {})
    unresolved = next_event(old)
    writer.append([old, unresolved])
    associations.associate(
        (
            RepositoryAssociation(
                kind="journal",
                record_id=str(old.event_id),
                origin=RepositoryOrigin(ONE),
            ),
        )
    )
    later = next_event(old)
    writer.append([later])
    assert associations.origin_for("journal", str(later.event_id)) is None


def test_historic_path_mapping_does_not_establish_new_write_provenance(
    stores: tuple[Store, RepositoryAssociations],
) -> None:
    writer, associations = stores
    old = recorder().entry("pr.observed", "head", {})
    writer.append([old])
    associations.associate(
        (
            RepositoryAssociation(
                kind="journal",
                record_id=str(old.event_id),
                origin=RepositoryOrigin("one.example/new/name"),
            ),
        )
    )
    later = next_event(old)
    writer.append([later])
    assert associations.origin_for("journal", str(later.event_id)) is None


def test_concurrent_first_writers_cannot_split_a_run_between_hosts(
    database_url: str, engine: sa.Engine
) -> None:
    first = recorder(ONE).entry("pr.observed", "head", {})
    second = replace(next_event(first), origin=TWO)
    start = Barrier(2)

    def append(entry: JournalEntry) -> bool:
        writer = SqlAlchemyJournal(database_url)
        try:
            start.wait(timeout=10)
            writer.append([entry])
            return True
        except AssociationConflictError:
            return False
        finally:
            writer._engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(append, (first, second)))
    assert sorted(results) == [False, True]
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count())
                .select_from(journal)
                .where(journal.c.workflow_id == first.workflow_id)
            ).scalar_one()
            == 1
        )


def test_an_unknown_observation_cannot_inherit_a_known_origin(
    stores: tuple[Store, RepositoryAssociations],
) -> None:
    writer, associations = stores
    known = recorder(ONE).entry("pr.observed", "head", {})
    writer.append([known])
    unknown = replace(next_event(known), origin_asserted=True)
    with pytest.raises(AssociationConflictError):
        writer.append([unknown])
    with pytest.raises(AssociationConflictError):
        writer.append([replace(known, origin=None, origin_asserted=True)])
    assert not writer.has_event(unknown.event_id)
    assert associations.origin_for("journal", str(unknown.event_id)) is None


def test_an_unknown_observation_starts_a_legacy_run(
    stores: tuple[Store, RepositoryAssociations],
) -> None:
    writer, associations = stores
    unknown = replace(
        recorder().entry("pr.observed", "head", {}), origin_asserted=True
    )
    writer.append([unknown])
    writer.append([unknown])
    later = next_event(unknown)
    writer.append([later])
    assert associations.origin_for("journal", str(unknown.event_id)) is None
    assert associations.origin_for("journal", str(later.event_id)) is None
