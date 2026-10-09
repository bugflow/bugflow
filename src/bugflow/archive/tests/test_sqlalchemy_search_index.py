"""Tests of the Postgres search index, against a real database.

The other search tests match with Python. Here Postgres does the matching,
so this is where the two are shown to give the same results as pyposlib's
search over the same archive on disk.

Skipped unless DATABASE_URL names a Postgres server.
"""

import time
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from pyposlib.search import DiskArchiveSearch

from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.archive.domain.models.indexed_file import (
    FoundLine,
    IndexedFile,
)
from bugflow.archive.infrastructure.in_memory_bindings import InMemoryBindings
from bugflow.archive.infrastructure.in_memory_kept_events import (
    InMemoryKeptEvents,
)
from bugflow.archive.infrastructure.pyposlib_keeping import PyposlibKeeping
from bugflow.archive.infrastructure.pyposlib_searching import PyposlibSearching
from bugflow.archive.infrastructure.sqlalchemy_search_index import (
    SqlAlchemyIndexedFiles,
    SqlAlchemyIndexPositions,
)
from bugflow.archive.tests.sealed_scope import LEDGER, Scope
from bugflow.shared.infrastructure.in_memory_object_store import (
    InMemoryObjectStore,
)

POEM = b"the first line\nthe second line\nand a third, with Line\n"
NOTES = b"first things first\n\nlast\n"


def test_a_file_s_lines_read_back_in_order_and_once(
    engine: sa.Engine, database_url: str
) -> None:
    files = SqlAlchemyIndexedFiles(database_url)
    files.keep(IndexedFile(cid="bafyone", lines=("a first", "b", "c first")))
    files.keep(IndexedFile(cid="bafytwo", lines=None))
    files.keep(IndexedFile(cid="bafyone", lines=("replaced",)))

    assert files.indexed(["bafyone", "bafytwo", "bafynone"]) == {
        "bafyone",
        "bafytwo",
    }
    assert files.find(["bafytwo", "bafyone"], "first", "literal", 10) == [
        FoundLine(position=1, number=1, text="a first"),
        FoundLine(position=1, number=3, text="c first"),
    ]


def test_hits_come_in_the_order_asked_then_by_line_up_to_the_limit(
    engine: sa.Engine, database_url: str
) -> None:
    files = SqlAlchemyIndexedFiles(database_url)
    files.keep(IndexedFile(cid="bafyx", lines=("x1 hit", "x2", "x3 hit")))
    files.keep(IndexedFile(cid="bafyy", lines=("y1 hit",)))

    found = files.find(["bafyy", "bafyx", "bafyy"], "hit", "literal", 3)
    assert [(line.position, line.number) for line in found] == [
        (0, 1),
        (1, 1),
        (1, 3),
    ]
    assert files.find(["bafyx"], "^x[13]", "regex", 10) == [
        FoundLine(position=0, number=1, text="x1 hit"),
        FoundLine(position=0, number=3, text="x3 hit"),
    ]
    assert files.find([], "hit", "literal", 10) == []


def test_an_expression_postgres_does_not_take_is_refused_as_request(
    engine: sa.Engine, database_url: str
) -> None:
    files = SqlAlchemyIndexedFiles(database_url)
    files.keep(IndexedFile(cid="bafyz", lines=("z",)))
    with pytest.raises(ArchiveRefusedError) as refused:
        files.find(["bafyz"], "(z", "regex", 10)
    assert refused.value.kind == "request"


ANOTHER = "2b3c4d5e-6f70-4a8b-9c0d-1e2f3a4b5c6d"


def test_a_search_that_outruns_its_time_is_refused_and_the_next_answers(
    engine: sa.Engine, database_url: str
) -> None:
    # This regular expression is slow in Postgres. It matches only a line whose
    # length is not a prime number, and 30,011 is prime, so Postgres tries
    # every possibility before giving up.
    files = SqlAlchemyIndexedFiles(database_url, within_seconds=0.2)
    files.keep(IndexedFile(cid="bafylong", lines=("a" * 30011, "short")))
    began = time.monotonic()
    with pytest.raises(ArchiveRefusedError) as refused:
        files.find(["bafylong"], r"^(aa+)\1+$", "regex", 10)
    assert refused.value.kind == "request"
    assert "0.2 seconds" in str(refused.value)
    assert time.monotonic() - began < 5
    # The time limit applied to that search only. The same connection pool runs
    # the next search normally.
    assert files.find(["bafylong"], "short", "literal", 10) == [
        FoundLine(position=0, number=2, text="short")
    ]
    with engine.connect() as connection:
        assert (
            connection.execute(sa.text("SHOW statement_timeout")).scalar()
            == "0"
        )


def test_a_position_only_advances(
    engine: sa.Engine, database_url: str
) -> None:
    """The recorded position never goes down. This uses a ledger id of its
    own, because the comparison test below shares the database and needs
    LEDGER to start with no position.
    """
    positions = SqlAlchemyIndexPositions(database_url)
    assert positions.position(ANOTHER) == 0
    positions.advance(ANOTHER, 3)
    positions.advance(ANOTHER, 2)
    assert positions.position(ANOTHER) == 3


QUERIES: list[tuple[str, dict[str, Any]]] = [
    ("first", {}),
    ("Line", {}),
    ("line", {"limit": 2}),
    ("(fir|sec)ond?", {"mode": "regex"}),
    ("^the", {"mode": "regex"}),
    ("nothing of the sort", {}),
]


@pytest.mark.parametrize(("query", "options"), QUERIES)
def test_the_postgres_index_answers_what_the_library_finds_on_disk(
    engine: sa.Engine,
    database_url: str,
    tmp_path: Path,
    query: str,
    options: dict[str, Any],
) -> None:
    """The index, with Postgres matching, returns the same results in the same
    order as pyposlib's search over the same archive on disk.
    """
    scope = Scope(tmp_path)
    bindings = InMemoryBindings()
    bindings.save(
        ArchiveBinding(ledger_id=LEDGER, forge="github", repo="some/one")
    )
    keeping = PyposlibKeeping(InMemoryKeptEvents(), InMemoryObjectStore())
    for item, files in (
        ("poem", {"poem.txt": POEM, "notes/notes.txt": NOTES}),
        ("picture", {"blob.bin": b"\xff\xfe\x00", "readme.txt": b"a first\n"}),
    ):
        keeping.append(LEDGER, *scope.seal(item, files), {}, "someone")
    searching = PyposlibSearching(
        keeping,
        SqlAlchemyIndexedFiles(database_url),
        SqlAlchemyIndexPositions(database_url),
    )
    searching.catch_up(LEDGER)

    hits = [
        {
            "ref": hit.ref,
            "range": {"lines": [hit.first_line, hit.last_line]},
            "passage": hit.passage,
        }
        for hit in searching.search(LEDGER, query, **options)
    ]
    assert hits == DiskArchiveSearch(scope.archive).search(query, **options)
