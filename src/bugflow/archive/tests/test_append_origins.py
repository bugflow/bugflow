"""Archive provenance survives keeper retries and host restarts."""

import uuid
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest

from bugflow.archive.domain import facts
from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.archive.dtos.append_event import AppendEventRequest
from bugflow.archive.infrastructure.in_memory_bindings import InMemoryBindings
from bugflow.archive.infrastructure.in_memory_kept_events import (
    InMemoryKeptEvents,
)
from bugflow.archive.infrastructure.pyposlib_keeping import PyposlibKeeping
from bugflow.archive.infrastructure.role_archive_access import (
    RoleArchiveAccess,
)
from bugflow.archive.tests import (
    test_an_append_is_admitted_verified_and_recorded as original,
)
from bugflow.archive.tests.sealed_scope import Scope, Sent
from bugflow.archive.usecases.append_event import AppendEventUseCase
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.repositories.repository_associations import (
    RepositoryAssociations,
)
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal
from bugflow.shared.infrastructure.in_memory_object_store import (
    InMemoryObjectStore,
)
from bugflow.shared.infrastructure.in_memory_repository_associations import (
    InMemoryRepositoryAssociations,
)
from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal
from bugflow.shared.infrastructure.sqlalchemy_repository_associations import (
    SqlAlchemyRepositoryAssociations,
)


@pytest.fixture(params=["memory", "postgres"])
def stores(
    request: pytest.FixtureRequest,
) -> tuple[RecordingService, RepositoryAssociations]:
    if request.param == "memory":
        associations = InMemoryRepositoryAssociations()
        return InMemoryJournal(associations=associations), associations
    request.getfixturevalue("engine")
    url = request.getfixturevalue("database_url")
    return SqlAlchemyJournal(url), SqlAlchemyRepositoryAssociations(url)


class Archive:
    def __init__(self, writer: RecordingService) -> None:
        self.writer = writer
        self.bindings = InMemoryBindings()
        self.events = InMemoryKeptEvents()
        self.keeper = PyposlibKeeping(self.events, InMemoryObjectStore())
        self.clock = original.TickingClock()

    def bind(self, ledger: str, origin: str | None) -> None:
        self.bindings.save(
            ArchiveBinding(
                ledger_id=ledger,
                forge="forgejo",
                repo="team/repo",
                origin=origin,
            )
        )

    def case(self, process: str) -> AppendEventUseCase:
        return AppendEventUseCase(
            self.bindings,
            RoleArchiveAccess(
                original.ARCHIVE_READER, original.ARCHIVE_WRITER
            ),
            self.keeper,
            self.writer,
            self.clock,
            process,
        )


def request(ledger: str, sent: Sent) -> AppendEventRequest:
    name, data, files = sent
    return AppendEventRequest(
        ledger_id=ledger,
        caller=original.WRITER,
        name=name,
        data=data,
        files=files,
        claims={"remote": "https://untrusted.example/other/repo"},
    )


def test_sealed_fact_uses_binding_and_retries_across_processes(
    stores: tuple[RecordingService, RepositoryAssociations], tmp_path: Path
) -> None:
    writer, associations = stores
    ledger = str(uuid.uuid4())
    sent = Scope(tmp_path, ledger).seal("first", {"a.txt": b"content"})
    archive = Archive(writer)
    archive.bind(ledger, "one.example/team/repo")
    assert (
        archive.case("first-process").execute(request(ledger, sent)).appended
    )
    assert (
        not archive.case("next-process")
        .execute(request(ledger, sent))
        .appended
    )
    identifier = facts.sealed_id(ledger, sent[0])
    assert (
        str(associations.origin_for("journal", str(identifier)))
        == "one.example/team/repo"
    )
    assert len(archive.events.of_ledger(ledger)) == 1


def test_same_process_handles_equal_paths_on_different_hosts(
    stores: tuple[RecordingService, RepositoryAssociations], tmp_path: Path
) -> None:
    writer, associations = stores
    archive = Archive(writer)
    case = archive.case("one-process")
    for host in ("one.example", "two.example"):
        ledger = str(uuid.uuid4())
        origin = f"{host}/team/repo"
        archive.bind(ledger, origin)
        sent = Scope(tmp_path / host, ledger).seal(
            "first", {"a.txt": b"content"}
        )
        case.execute(request(ledger, sent))
        assert (
            str(
                associations.origin_for(
                    "journal", str(facts.sealed_id(ledger, sent[0]))
                )
            )
            == origin
        )


def test_retry_after_mapping_a_ledger_does_not_retag_an_old_fact(
    stores: tuple[RecordingService, RepositoryAssociations], tmp_path: Path
) -> None:
    writer, associations = stores
    ledger = str(uuid.uuid4())
    sent = Scope(tmp_path, ledger).seal("first", {"a.txt": b"content"})
    archive = Archive(writer)
    archive.bind(ledger, None)
    archive.case("legacy-process").execute(request(ledger, sent))
    archive.bind(ledger, "one.example/team/repo")
    assert (
        not archive.case("canonical-process")
        .execute(request(ledger, sent))
        .appended
    )
    assert (
        associations.origin_for(
            "journal", str(facts.sealed_id(ledger, sent[0]))
        )
        is None
    )


class InterruptOnce:
    def __init__(self, writer: RecordingService) -> None:
        self.writer = writer
        self.failed = False

    def has_event(self, identifier: UUID) -> bool:
        return self.writer.has_event(identifier)

    def append(self, entries: Sequence[JournalEntry]) -> None:
        if not self.failed:
            self.failed = True
            raise RuntimeError("journal unavailable")
        self.writer.append(entries)


def test_retry_repairs_a_fact_missing_after_keeper_success(
    stores: tuple[RecordingService, RepositoryAssociations], tmp_path: Path
) -> None:
    writer, associations = stores
    ledger = str(uuid.uuid4())
    sent = Scope(tmp_path, ledger).seal("first", {"a.txt": b"content"})
    archive = Archive(InterruptOnce(writer))
    archive.bind(ledger, "one.example/team/repo")
    with pytest.raises(RuntimeError, match="unavailable"):
        archive.case("first-process").execute(request(ledger, sent))
    identifier = facts.sealed_id(ledger, sent[0])
    assert len(archive.events.of_ledger(ledger)) == 1
    assert not writer.has_event(identifier)
    assert (
        not archive.case("next-process")
        .execute(request(ledger, sent))
        .appended
    )
    assert (
        str(associations.origin_for("journal", str(identifier)))
        == "one.example/team/repo"
    )


def test_refusal_records_binding_origin_and_no_event(
    stores: tuple[RecordingService, RepositoryAssociations], tmp_path: Path
) -> None:
    writer, associations = stores
    ledger = str(uuid.uuid4())
    sent = Scope(tmp_path, ledger).seal("first", {"a.txt": b"content"})
    archive = Archive(writer)
    archive.bind(ledger, "one.example/team/repo")
    when = archive.clock._now
    with pytest.raises(ArchiveRefusedError) as error:
        archive.case("process").execute(
            request(ledger, sent).model_copy(update={"files": {}})
        )

    identifier = facts.refused_id(
        ledger, sent[0], error.value.kind, when + timedelta(seconds=1)
    )
    assert (
        str(associations.origin_for("journal", str(identifier)))
        == "one.example/team/repo"
    )
    assert archive.events.of_ledger(ledger) == []


def test_access_refusal_records_nothing(
    stores: tuple[RecordingService, RepositoryAssociations], tmp_path: Path
) -> None:
    writer, _ = stores
    ledger = str(uuid.uuid4())
    sent = Scope(tmp_path, ledger).seal("first", {"a.txt": b"content"})
    archive = Archive(writer)
    archive.bind(ledger, "one.example/team/repo")
    with pytest.raises(ArchiveRefusedError, match="Not allowed"):
        archive.case("process").execute(
            request(ledger, sent).model_copy(
                update={"caller": original.READER}
            )
        )
    assert not writer.has_event(facts.sealed_id(ledger, sent[0]))
    assert archive.events.of_ledger(ledger) == []


class StaleLookup:
    """Model two requests that both checked before either wrote its fact."""

    def __init__(self, writer: RecordingService) -> None:
        self.writer = writer

    def has_event(self, identifier: UUID) -> bool:
        return False

    def append(self, entries: Sequence[JournalEntry]) -> None:
        self.writer.append(entries)


def test_duplicate_after_stale_lookup_uses_the_same_scope(
    stores: tuple[RecordingService, RepositoryAssociations], tmp_path: Path
) -> None:
    writer, associations = stores
    ledger = str(uuid.uuid4())
    sent = Scope(tmp_path, ledger).seal("first", {"a.txt": b"content"})
    archive = Archive(StaleLookup(writer))
    archive.bind(ledger, "one.example/team/repo")
    archive.case("first-process").execute(request(ledger, sent))
    archive.case("second-process").execute(request(ledger, sent))
    identifier = facts.sealed_id(ledger, sent[0])
    assert str(associations.origin_for("journal", str(identifier))) == (
        "one.example/team/repo"
    )
    assert len(archive.events.of_ledger(ledger)) == 1


def test_historical_path_mismatch_refuses_before_keeper_storage(
    stores: tuple[RecordingService, RepositoryAssociations], tmp_path: Path
) -> None:
    writer, _ = stores
    ledger = str(uuid.uuid4())
    sent = Scope(tmp_path, ledger).seal("first", {"a.txt": b"content"})
    archive = Archive(writer)
    # Historical mappings can differ from the retained binding row.
    archive.bindings._bound[ledger] = ArchiveBinding(
        ledger_id=ledger,
        forge="forgejo",
        repo="old/path",
        origin="one.example/team/repo",
    )
    with pytest.raises(ArchiveRefusedError, match="does not match"):
        archive.case("process").execute(request(ledger, sent))
    assert not writer.has_event(facts.sealed_id(ledger, sent[0]))
    assert archive.events.of_ledger(ledger) == []
