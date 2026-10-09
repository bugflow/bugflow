"""Under version 2 of the remote archive protocol a client puts the
blocks of an item's files first and appends the event alone.

The use cases run over the real keeper, pyposlib's behind its adapter,
with storage, the puts and the journal in memory.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pyposlib import cid

from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.archive.dtos.append_event import AppendEventRequest
from bugflow.archive.dtos.missing_blocks import MissingBlocksRequest
from bugflow.archive.dtos.put_block import PutBlockRequest
from bugflow.archive.infrastructure.in_memory_bindings import InMemoryBindings
from bugflow.archive.infrastructure.in_memory_block_puts import (
    InMemoryBlockPuts,
)
from bugflow.archive.infrastructure.in_memory_kept_events import (
    InMemoryKeptEvents,
)
from bugflow.archive.infrastructure.pyposlib_keeping import PyposlibKeeping
from bugflow.archive.infrastructure.role_archive_access import (
    RoleArchiveAccess,
)
from bugflow.archive.tests.sealed_scope import LEDGER, Scope
from bugflow.archive.usecases.append_event import AppendEventUseCase
from bugflow.archive.usecases.missing_blocks import MissingBlocksUseCase
from bugflow.archive.usecases.put_block import PutBlockUseCase
from bugflow.shared.domain.values.caller import Caller
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal
from bugflow.shared.infrastructure.in_memory_object_store import (
    InMemoryObjectStore,
)

#: The roles the access adapter is told open the archives.
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


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 8, tzinfo=UTC)


class Keeping:
    """A bound ledger with nothing kept yet, and the three use cases a
    version 2 seal goes through."""

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
        access = RoleArchiveAccess(ARCHIVE_READER, ARCHIVE_WRITER)
        self.store = InMemoryObjectStore()
        self.puts = InMemoryBlockPuts()
        self.journal = InMemoryJournal()
        keeping = PyposlibKeeping(InMemoryKeptEvents(), self.store)
        self.held = MissingBlocksUseCase(bindings, access, keeping)
        self.put = PutBlockUseCase(bindings, access, keeping, self.puts)
        self.append = AppendEventUseCase(
            bindings, access, keeping, self.journal, Clock(), "run"
        )

    def missing(
        self, cids: list[str], caller: Caller = WRITER, ledger: str = LEDGER
    ) -> list[str]:
        return list(
            self.held.execute(
                MissingBlocksRequest(
                    ledger_id=ledger, caller=caller, cids=tuple(cids)
                )
            ).missing
        )

    def put_block(
        self,
        block: str,
        data: bytes,
        caller: Caller = WRITER,
        ledger: str = LEDGER,
    ) -> bool:
        return self.put.execute(
            PutBlockRequest(
                ledger_id=ledger, caller=caller, cid=block, data=data
            )
        ).new

    def append_alone(self, name: str, data: bytes) -> int:
        return self.append.execute(
            AppendEventRequest(
                ledger_id=LEDGER,
                caller=WRITER,
                name=name,
                data=data,
                files={},
                claims=CLAIMS,
            )
        ).events


def refused(operation: object) -> str:
    assert callable(operation)
    with pytest.raises(ArchiveRefusedError) as refusal:
        operation()
    return refusal.value.kind


def test_a_file_of_several_chunks_is_held_block_by_block(
    tmp_path: Path,
) -> None:
    """The keeper is asked which blocks it lacks, is put each, and takes
    the event once the file's node and every leaf beneath it are held;
    the node alone is not enough."""
    keeping = Keeping()
    big = bytes(i % 251 for i in range(2 * cid.CHUNK_SIZE + 1))
    name, data, _ = Scope(tmp_path).seal("first", {"big": big})
    blocks = cid.blocks(big)
    root = cid.cid_bytes(big)
    assert set(blocks) == {root, *blocks} and len(blocks) == 4
    assert keeping.missing(sorted(blocks)) == sorted(blocks)
    assert keeping.put_block(root, blocks[root]) is True
    assert refused(lambda: keeping.append_alone(name, data)) == "entry"
    for block, held in blocks.items():
        keeping.put_block(block, held)
    assert keeping.missing(sorted(blocks)) == []
    assert keeping.append_alone(name, data) == 1
    assert len(keeping.puts.of_ledger(LEDGER)) == 4
    # The append sent too early is a refusal recorded against the
    # ledger's repository, as any other; the puts themselves are not.
    assert [fact.event_type for fact in keeping.journal.entries] == [
        "archive.refused",
        "archive.sealed",
    ]


def test_what_is_put_is_held_to_its_cid(tmp_path: Path) -> None:
    keeping = Keeping()
    leaf = cid.cid_bytes(b"first")
    assert refused(lambda: keeping.put_block(leaf, b"other")) == "entry"
    assert keeping.puts.of_ledger(LEDGER) == []
    assert not keeping.store.objects
    assert refused(lambda: keeping.missing(["not a cid"])) == "request"


def test_a_put_is_the_first_half_of_an_append_and_needs_its_role() -> None:
    keeping = Keeping()
    leaf = cid.cid_bytes(b"first")
    assert refused(lambda: keeping.put_block(leaf, b"first", READER)) == (
        "access"
    )
    assert refused(lambda: keeping.missing([leaf], READER)) == "access"
    assert (
        refused(lambda: keeping.put_block(leaf, b"first", WRITER, UNBOUND))
        == "absent"
    )
    assert keeping.puts.of_ledger(LEDGER) == []
