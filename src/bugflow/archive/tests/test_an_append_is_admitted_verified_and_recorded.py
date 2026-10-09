"""Tests of the append use case: it checks the caller's role, has the keeper
check the event, and writes the outcome to the journal.

It runs on the real keeper (pyposlib's), with storage and the journal in
memory.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

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
from bugflow.archive.tests.sealed_scope import LEDGER, Scope, Sent
from bugflow.archive.usecases.append_event import AppendEventUseCase
from bugflow.shared.domain.values.caller import Caller
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal
from bugflow.shared.infrastructure.in_memory_object_store import (
    InMemoryObjectStore,
)

#: The role names these tests give the access adapter.
ARCHIVE_READER = "an-archive-reader"
ARCHIVE_WRITER = "an-archive-writer"

UNBOUND = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
WRITER = Caller(
    subject="someone", client="a-client", roles=frozenset({ARCHIVE_WRITER})
)
READER = Caller(
    subject="another", client="a-client", roles=frozenset({ARCHIVE_READER})
)
CLAIMS = {"remote": "git@forge.example:some/one.git", "dirty": "false"}


class TickingClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 10, 1, tzinfo=UTC)

    def now(self) -> datetime:
        self._now += timedelta(seconds=1)
        return self._now


class Keeping:
    """A registered ledger with nothing stored yet, and the append use case
    set up over it.
    """

    def __init__(self) -> None:
        bindings = InMemoryBindings()
        bindings.save(
            ArchiveBinding(
                ledger_id=LEDGER,
                forge="github",
                repo="some/one",
                scope="projects/example",
            )
        )
        self.events = InMemoryKeptEvents()
        self.journal = InMemoryJournal()
        self.append = AppendEventUseCase(
            bindings,
            RoleArchiveAccess(ARCHIVE_READER, ARCHIVE_WRITER),
            PyposlibKeeping(self.events, InMemoryObjectStore()),
            self.journal,
            TickingClock(),
            "run",
        )

    def send(
        self,
        sent: Sent,
        caller: Caller = WRITER,
        ledger: str = LEDGER,
        files: dict[str, bytes] | None = None,
    ) -> object:
        name, data, enrolled = sent
        return self.append.execute(
            AppendEventRequest(
                ledger_id=ledger,
                caller=caller,
                name=name,
                data=data,
                files=enrolled if files is None else files,
                claims=CLAIMS,
            )
        )


def refused(operation: object) -> str:
    assert callable(operation)
    with pytest.raises(ArchiveRefusedError) as refusal:
        operation()
    return refusal.value.kind


def test_an_event_kept_is_a_fact_against_the_ledger_s_repository(
    tmp_path: Path,
) -> None:
    scope = Scope(tmp_path)
    sent = scope.seal("first", {"a.txt": b"first"})
    keeping = Keeping()

    keeping.send(sent)

    head, root = scope.head_and_root()
    (fact,) = keeping.journal.entries
    assert (fact.event_type, fact.forge, fact.repo) == (
        "archive.sealed",
        "github",
        "some/one",
    )
    assert fact.payload == {
        "ledger_id": LEDGER,
        "scope": "projects/example",
        "name": sent[0],
        "head": head,
        "root": root,
        "events": 1,
        "files": 1,
        "bytes": 5,
        "caller": "someone",
        "client": "a-client",
        "claims": CLAIMS,
    }
    assert len(keeping.events.of_ledger(LEDGER)) == 1


def test_an_event_sent_again_is_one_event_and_one_fact(tmp_path: Path) -> None:
    sent = Scope(tmp_path).seal("first", {"a.txt": b"first"})
    keeping = Keeping()
    keeping.send(sent)

    keeping.send(sent)

    assert len(keeping.events.of_ledger(LEDGER)) == 1
    assert [f.event_type for f in keeping.journal.entries] == [
        "archive.sealed"
    ]


def test_an_event_the_keeper_refuses_is_recorded_with_its_kind(
    tmp_path: Path,
) -> None:
    sent = Scope(tmp_path).seal("first", {"a.txt": b"first"})
    keeping = Keeping()

    kind = refused(lambda: keeping.send(sent, files={}))

    (fact,) = keeping.journal.entries
    assert kind == "entry"
    assert (fact.event_type, fact.payload["kind"]) == (
        "archive.refused",
        "entry",
    )
    assert fact.payload["name"] == sent[0]
    assert keeping.events.of_ledger(LEDGER) == []


def test_refused_twice_is_two_facts(tmp_path: Path) -> None:
    sent = Scope(tmp_path).seal("first", {"a.txt": b"first"})
    keeping = Keeping()

    for _ in range(2):
        refused(lambda: keeping.send(sent, files={}))

    assert len({fact.event_id for fact in keeping.journal.entries}) == 2


@pytest.mark.parametrize("ledger", [LEDGER, UNBOUND])
def test_one_who_may_only_read_cannot_append(
    tmp_path: Path, ledger: str
) -> None:
    sent = Scope(tmp_path).seal("first", {"a.txt": b"first"})
    keeping = Keeping()

    assert refused(lambda: keeping.send(sent, READER, ledger)) == "access"
    assert keeping.journal.entries == []
    assert keeping.events.of_ledger(ledger) == []


def test_a_ledger_nobody_bound_keeps_nothing_and_records_nothing(
    tmp_path: Path,
) -> None:
    """An append to a ledger that is not registered stores nothing and writes
    nothing to the journal.
    """
    sent = Scope(tmp_path, UNBOUND).seal("first", {"a.txt": b"first"})
    keeping = Keeping()

    assert refused(lambda: keeping.send(sent, ledger=UNBOUND)) == "absent"
    assert keeping.journal.entries == []
    assert keeping.events.of_ledger(UNBOUND) == []
