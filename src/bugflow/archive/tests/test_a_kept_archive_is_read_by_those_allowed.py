"""What is kept of a ledger is read through use cases that ask who is
calling and whether the ledger is bound.

The use cases run over the real keeper, pyposlib's behind its adapter,
with storage in memory: what they hand back is what a seal sent.
"""

from pathlib import Path

import pytest

from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.archive.dtos.describe_archive import DescribeArchiveRequest
from bugflow.archive.dtos.fetch_event import FetchEventRequest
from bugflow.archive.dtos.read_archived import ReadArchivedRequest
from bugflow.archive.infrastructure.in_memory_bindings import InMemoryBindings
from bugflow.archive.infrastructure.in_memory_kept_events import (
    InMemoryKeptEvents,
)
from bugflow.archive.infrastructure.pyposlib_keeping import PyposlibKeeping
from bugflow.archive.infrastructure.role_archive_access import (
    RoleArchiveAccess,
)
from bugflow.archive.tests.sealed_scope import LEDGER, Scope
from bugflow.archive.usecases.describe_archive import (
    DescribeArchiveUseCase,
)
from bugflow.archive.usecases.fetch_event import FetchEventUseCase
from bugflow.archive.usecases.read_archived import ReadArchivedUseCase
from bugflow.shared.domain.values.caller import Caller
from bugflow.shared.infrastructure.in_memory_object_store import (
    InMemoryObjectStore,
)

#: The roles the access adapter is told open the archives.
ARCHIVE_READER = "an-archive-reader"
ARCHIVE_WRITER = "an-archive-writer"

UNBOUND = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


def caller(*roles: str) -> Caller:
    return Caller(subject="someone", client="a-client", roles=frozenset(roles))


READER = caller(ARCHIVE_READER)
WRITER = caller(ARCHIVE_WRITER)
STRANGER = caller("some-other-role")


class Kept:
    """A bound ledger with two items kept, and the use cases over it."""

    def __init__(self, tmp_path: Path) -> None:
        self.scope = Scope(tmp_path)
        self.first = self.scope.seal("first", {"a.txt": b"first"})
        second = self.scope.seal("second", {"sub/c.txt": b"c"})
        bindings = InMemoryBindings()
        bindings.save(
            ArchiveBinding(ledger_id=LEDGER, forge="github", repo="some/one")
        )
        keeping = PyposlibKeeping(InMemoryKeptEvents(), InMemoryObjectStore())
        for sent in (self.first, second):
            keeping.append(LEDGER, *sent, {}, "someone")
        access = RoleArchiveAccess(ARCHIVE_READER, ARCHIVE_WRITER)
        self.describe = DescribeArchiveUseCase(bindings, access, keeping)
        self.fetch = FetchEventUseCase(bindings, access, keeping)
        self.read = ReadArchivedUseCase(bindings, access, keeping)


@pytest.fixture
def kept(tmp_path: Path) -> Kept:
    return Kept(tmp_path)


def refused(operation: object) -> str:
    assert callable(operation)
    with pytest.raises(ArchiveRefusedError) as refusal:
        operation()
    return refusal.value.kind


def test_a_reader_is_told_what_is_kept(kept: Kept) -> None:
    head, root = kept.scope.head_and_root()

    said = kept.describe.execute(
        DescribeArchiveRequest(ledger_id=LEDGER, caller=READER)
    )

    assert (said.ledger_id, said.events) == (LEDGER, 2)
    assert (said.head, said.root, said.erased) == (head, root, ())


def test_one_who_may_append_is_told_too(kept: Kept) -> None:
    """A client that seals asks what is kept before it sends."""
    said = kept.describe.execute(
        DescribeArchiveRequest(ledger_id=LEDGER, caller=WRITER)
    )

    assert said.events == 2


def test_what_is_kept_is_not_told_to_one_with_no_role(kept: Kept) -> None:
    for ledger in (LEDGER, UNBOUND):
        request = DescribeArchiveRequest(ledger_id=ledger, caller=STRANGER)
        assert refused(lambda r=request: kept.describe.execute(r)) == "access"


def test_a_ledger_nobody_bound_is_absent_to_a_reader(kept: Kept) -> None:
    request = DescribeArchiveRequest(ledger_id=UNBOUND, caller=READER)

    assert refused(lambda: kept.describe.execute(request)) == "absent"


def test_a_reader_fetches_an_event_as_the_ledger_holds_it(kept: Kept) -> None:
    fetched = kept.fetch.execute(
        FetchEventRequest(ledger_id=LEDGER, caller=READER, number=1)
    )

    assert fetched.data == kept.first[1]


def test_an_event_that_is_not_there_is_absent(kept: Kept) -> None:
    request = FetchEventRequest(ledger_id=LEDGER, caller=READER, number=3)

    assert refused(lambda: kept.fetch.execute(request)) == "absent"


def test_an_event_is_not_fetched_by_one_with_no_role(kept: Kept) -> None:
    request = FetchEventRequest(ledger_id=LEDGER, caller=STRANGER, number=1)

    assert refused(lambda: kept.fetch.execute(request)) == "access"


def test_a_reader_reads_a_file_by_its_cid_and_by_its_path(kept: Kept) -> None:
    cids = kept.scope.cids()

    by_cid = kept.read.execute(
        ReadArchivedRequest(
            ledger_id=LEDGER, caller=READER, cid=cids["first/a.txt"]
        )
    )
    by_path = kept.read.execute(
        ReadArchivedRequest(
            ledger_id=LEDGER,
            caller=READER,
            cid=cids["."],
            path="second/sub/c.txt",
        )
    )

    assert (by_cid.data, by_path.data) == (b"first", b"c")


def test_a_path_the_ledger_enrols_nothing_at_is_absent(kept: Kept) -> None:
    request = ReadArchivedRequest(
        ledger_id=LEDGER,
        caller=READER,
        cid=kept.scope.cids()["."],
        path="nowhere",
    )

    assert refused(lambda: kept.read.execute(request)) == "absent"


def test_nothing_is_read_by_one_with_no_role(kept: Kept) -> None:
    request = ReadArchivedRequest(
        ledger_id=LEDGER, caller=STRANGER, cid=kept.scope.cids()["."]
    )

    assert refused(lambda: kept.read.execute(request)) == "access"
