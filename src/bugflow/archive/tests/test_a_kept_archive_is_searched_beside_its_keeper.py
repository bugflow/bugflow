"""Tests of search.

Search is answered from an index. The index runs on the real keeper
(pyposlib's), with all storage in memory.

The results are compared with pyposlib's own search over the same archive
on disk. The protocol requires that two implementations give the same
results in the same order for the ``literal`` and ``regex`` modes (section
12, "Conformance").
"""

from pathlib import Path
from typing import Any

import pytest
from pyposlib.search import DiskArchiveSearch

from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.archive.dtos.index_archive import IndexArchiveRequest
from bugflow.archive.dtos.search_archive import SearchArchiveRequest
from bugflow.archive.infrastructure.in_memory_bindings import InMemoryBindings
from bugflow.archive.infrastructure.in_memory_kept_events import (
    InMemoryKeptEvents,
)
from bugflow.archive.infrastructure.in_memory_search_index import (
    InMemoryIndexedFiles,
    InMemoryIndexPositions,
)
from bugflow.archive.infrastructure.pyposlib_keeping import PyposlibKeeping
from bugflow.archive.infrastructure.pyposlib_searching import PyposlibSearching
from bugflow.archive.infrastructure.role_archive_access import (
    RoleArchiveAccess,
)
from bugflow.archive.tests.sealed_scope import LEDGER, Scope
from bugflow.archive.usecases.index_archive import IndexArchiveUseCase
from bugflow.archive.usecases.search_archive import SearchArchiveUseCase
from bugflow.shared.domain.values.caller import Caller
from bugflow.shared.infrastructure.in_memory_object_store import (
    InMemoryObjectStore,
)

#: The role names these tests give the access adapter.
ARCHIVE_READER = "an-archive-reader"
ARCHIVE_WRITER = "an-archive-writer"

UNBOUND = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
OTHER_LEDGER = "2b3c4d5e-6f70-4a8b-9c0d-1e2f3a4b5c6d"

POEM = b"the first line\nthe second line\nand a third, with Line\n"
NOTES = b"first things first\n\nlast\n"
BINARY = b"\xff\xfe not text \x00"


def caller(*roles: str) -> Caller:
    return Caller(subject="someone", client="a-client", roles=frozenset(roles))


READER = caller(ARCHIVE_READER)
STRANGER = caller("some-other-role")


class Kept:
    """A registered ledger with two items stored, the search index over it,
    and pyposlib's own search over the same archive on disk for comparison.
    """

    def __init__(self, tmp_path: Path, ledger: str = LEDGER) -> None:
        self.scope = Scope(tmp_path, ledger)
        self.ledger = ledger
        self.bindings = InMemoryBindings()
        self.bindings.save(
            ArchiveBinding(ledger_id=ledger, forge="github", repo="some/one")
        )
        self.events = InMemoryKeptEvents()
        self.store = InMemoryObjectStore()
        self.keeping = PyposlibKeeping(self.events, self.store)
        self.files = InMemoryIndexedFiles()
        self.positions = InMemoryIndexPositions()
        self.searching = PyposlibSearching(
            self.keeping, self.files, self.positions
        )
        self.index = IndexArchiveUseCase(self.bindings, self.searching)
        self.search = SearchArchiveUseCase(
            self.bindings,
            RoleArchiveAccess(ARCHIVE_READER, ARCHIVE_WRITER),
            self.searching,
        )
        self.on_disk = DiskArchiveSearch(self.scope.archive)

    def seal(self, item: str, files: dict[str, bytes]) -> None:
        sent = self.scope.seal(item, files)
        self.keeping.append(self.ledger, *sent, {}, "someone")

    def catch_up(self) -> tuple[int, int]:
        caught = self.index.execute(IndexArchiveRequest(ledger_id=self.ledger))
        return caught.events, caught.files

    def hits(
        self,
        query: str,
        mode: str | None = None,
        limit: int | None = None,
        within: str | None = None,
    ) -> list[dict[str, Any]]:
        found = self.search.execute(
            SearchArchiveRequest(
                ledger_id=self.ledger,
                caller=READER,
                query=query,
                mode=mode,
                limit=limit,
                within=within,
            )
        ).hits
        return [
            {
                "ref": hit.ref,
                "range": {"lines": [hit.first_line, hit.last_line]},
                "passage": hit.passage,
            }
            for hit in found
        ]


@pytest.fixture
def kept(tmp_path: Path) -> Kept:
    kept = Kept(tmp_path)
    kept.seal("poem", {"poem.txt": POEM, "notes/notes.txt": NOTES})
    kept.seal("picture", {"blob.bin": BINARY, "readme.txt": b"a first\n"})
    kept.catch_up()
    return kept


QUERIES: list[tuple[str, dict[str, Any]]] = [
    ("first", {}),
    ("Line", {}),
    ("line", {"limit": 2}),
    ("(fir|sec)ond?", {"mode": "regex"}),
    ("^the", {"mode": "regex"}),
    ("nothing of the sort", {}),
]


@pytest.mark.parametrize(("query", "options"), QUERIES)
def test_the_index_answers_what_the_library_finds_on_disk(
    kept: Kept, query: str, options: dict[str, Any]
) -> None:
    """The index and pyposlib's search over the same archive return the same
    results in the same order.
    """
    assert kept.hits(query, **options) == kept.on_disk.search(query, **options)


def test_a_hit_is_what_read_gives_at_its_reference(kept: Kept) -> None:
    """Each result quotes the archive exactly: reading the file it refers to,
    at the lines it gives, returns the result's text.
    """
    for hit in kept.hits("first"):
        assert isinstance(hit["ref"], str)
        cid, _, path = hit["ref"].removeprefix("ipfs://").partition("/")
        lines = kept.keeping.read(kept.ledger, cid, path).decode().split("\n")
        first, last = hit["range"]["lines"]
        assert hit["passage"] == "\n".join(lines[first - 1 : last])


def test_hits_are_in_the_archive_s_order_by_path_then_line(kept: Kept) -> None:
    refs = [hit["ref"] for hit in kept.hits("first")]
    assert [str(ref).rsplit("/", 1)[-1] for ref in refs] == [
        "readme.txt",
        "notes.txt",
        "poem.txt",
    ]
    assert kept.hits("line")[0]["range"] == {"lines": [1, 1]}


def test_a_search_within_an_item_sees_that_item_alone(kept: Kept) -> None:
    cids = kept.scope.cids()
    within_poem = kept.hits("first", within=cids["poem"])
    assert {str(hit["ref"]).rsplit("/", 1)[-1] for hit in within_poem} == {
        "poem.txt",
        "notes.txt",
    }
    assert within_poem == kept.on_disk.search("first", within=cids["poem"])
    with pytest.raises(ArchiveRefusedError) as refused:
        kept.hits(
            "first",
            within="bafkreifdwygomo7nwrunblacdo227rwbn65qtyg3cvw73c7zzqdh2tycz4",
        )
    assert refused.value.kind == "absent"


def test_a_file_that_is_not_text_gives_no_hit_and_is_read_once(
    kept: Kept,
) -> None:
    cids = kept.scope.cids()
    assert kept.hits("not text") == []
    assert kept.files.files[cids["picture/blob.bin"]].lines is None
    # A second catch-up finds nothing new to index.
    assert kept.catch_up() == (2, 0)


def test_a_mode_the_index_lacks_and_a_bad_expression_are_refused(
    kept: Kept,
) -> None:
    with pytest.raises(ArchiveRefusedError) as mode:
        kept.hits("first", mode="semantic")
    assert mode.value.kind == "mode"
    with pytest.raises(ArchiveRefusedError) as request:
        kept.hits("(first", mode="regex")
    assert request.value.kind == "request"
    with pytest.raises(ArchiveRefusedError) as empty:
        kept.hits("")
    assert empty.value.kind == "request"


def test_the_index_follows_the_ledger_by_its_event_count(
    tmp_path: Path,
) -> None:
    kept = Kept(tmp_path)
    assert kept.catch_up() == (0, 0)
    kept.seal("poem", {"poem.txt": POEM})
    assert kept.hits("first") == []
    assert kept.catch_up() == (1, 1)
    assert [hit["passage"] for hit in kept.hits("first")] == ["the first line"]
    kept.seal("notes", {"notes.txt": NOTES})
    # An index that has not caught up is missing the newest files. It never has
    # wrong content for older ones.
    assert len(kept.hits("first")) == 1
    assert kept.catch_up() == (2, 1)
    assert len(kept.hits("first")) == 2
    assert kept.positions.position(LEDGER) == 2


def test_a_file_two_ledgers_enrol_is_indexed_once(tmp_path: Path) -> None:
    first = Kept(tmp_path / "first")
    first.seal("poem", {"poem.txt": POEM})
    second = Kept(tmp_path / "second", OTHER_LEDGER)
    second.files, second.positions = first.files, first.positions
    second.searching = PyposlibSearching(
        second.keeping, first.files, first.positions
    )
    second.index = IndexArchiveUseCase(second.bindings, second.searching)
    second.search = SearchArchiveUseCase(
        second.bindings,
        RoleArchiveAccess(ARCHIVE_READER, ARCHIVE_WRITER),
        second.searching,
    )
    second.seal("verse", {"copy.txt": POEM})

    assert first.catch_up() == (1, 1)
    assert second.catch_up() == (1, 0)
    assert len(first.files.files) == 1
    assert [hit["ref"] for hit in second.hits("first")] != [
        hit["ref"] for hit in first.hits("first")
    ]


def test_a_search_takes_read_s_access(kept: Kept) -> None:
    for who, kind in ((STRANGER, "access"),):
        with pytest.raises(ArchiveRefusedError) as refused:
            kept.search.execute(
                SearchArchiveRequest(
                    ledger_id=kept.ledger, caller=who, query="first"
                )
            )
        assert refused.value.kind == kind
    with pytest.raises(ArchiveRefusedError) as unbound:
        kept.search.execute(
            SearchArchiveRequest(
                ledger_id=UNBOUND, caller=caller(ARCHIVE_WRITER), query="first"
            )
        )
    assert unbound.value.kind == "absent"


def test_an_unbound_ledger_is_not_indexed(kept: Kept) -> None:
    with pytest.raises(ArchiveRefusedError) as refused:
        kept.index.execute(IndexArchiveRequest(ledger_id=UNBOUND))
    assert refused.value.kind == "absent"
