"""An append asks the object store after its blocks, and writes them,
several at a time.

The store may be far from the host that keeps, and each call to it then
costs a round trip. An event of a thousand files asked after and
written one at a time took longer than a sealing client waits. The
stores here make that visible without a network: one lets no call
through until several are waiting together, so a keeper that calls one
at a time is stopped, and one counts what it is asked.
"""

import threading
from pathlib import Path

import pytest

from bugflow.archive.infrastructure.in_memory_kept_events import (
    InMemoryKeptEvents,
)
from bugflow.archive.infrastructure.pyposlib_keeping import (
    BLOCKS,
    PyposlibKeeping,
)
from bugflow.archive.tests.sealed_scope import LEDGER, Scope
from bugflow.shared.domain.errors import ObjectStoreError
from bugflow.shared.infrastructure.in_memory_object_store import (
    InMemoryObjectStore,
)

OTHER = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"

FOUR = {name: name.encode() for name in ("a.txt", "b.txt", "c.txt", "d.txt")}


class Counting(InMemoryObjectStore):
    """Counts each question and each write, by key."""

    def __init__(self) -> None:
        super().__init__()
        self.asked: list[str] = []
        self.written: list[str] = []

    def has(self, key: str) -> bool:
        self.asked.append(key)
        return super().has(key)

    def put(
        self,
        key: str,
        body: bytes,
        content_type: str = "application/json",
        content_encoding: str | None = "gzip",
    ) -> None:
        self.written.append(key)
        super().put(key, body, content_type, content_encoding)


class Together(InMemoryObjectStore):
    """Lets a call of the gated kind through only when ``parties`` of
    them wait at once: a caller that makes them one at a time waits for
    company that never comes, and the gate breaks."""

    def __init__(self, gated: str, parties: int) -> None:
        super().__init__()
        self._gated = gated
        self._gate = threading.Barrier(parties, timeout=5)
        self._left = parties

    def _wait(self, kind: str) -> None:
        if kind == self._gated and self._left > 0:
            self._left -= 1
            self._gate.wait()

    def has(self, key: str) -> bool:
        self._wait("has")
        return super().has(key)

    def put(
        self,
        key: str,
        body: bytes,
        content_type: str = "application/json",
        content_encoding: str | None = "gzip",
    ) -> None:
        self._wait("put")
        super().put(key, body, content_type, content_encoding)


def test_an_event_s_blocks_are_written_several_at_once(tmp_path: Path) -> None:
    scope = Scope(tmp_path)
    name, data, files = scope.seal("first", FOUR)
    events, store = InMemoryKeptEvents(), Together("put", 4)

    PyposlibKeeping(events, store).append(LEDGER, name, data, files, {}, "who")

    for path, body in FOUR.items():
        assert store.objects[BLOCKS + scope.cids()[f"first/{path}"]] == body


def test_files_already_held_are_asked_after_several_at_once(
    tmp_path: Path,
) -> None:
    """A keeper takes an event without the bytes of a file it holds, and
    has to ask the store whether it does. A second ledger enrolling the
    files of the first, sent without them, is that case."""
    first = Scope(tmp_path / "one").seal("first", FOUR)
    name, data, _ = Scope(tmp_path / "two", OTHER).seal("first", FOUR)
    events, held = InMemoryKeptEvents(), InMemoryObjectStore()
    PyposlibKeeping(events, held).append(LEDGER, *first, {}, "who")
    store = Together("has", 4)
    store.objects.update(held.objects)

    answer = PyposlibKeeping(events, store).append(
        OTHER, name, data, {}, {}, "who"
    )

    assert answer.appended


def test_a_block_the_store_holds_is_not_written_again(tmp_path: Path) -> None:
    """Two items that share a file's bytes share its block, which the
    second append finds held and leaves."""
    scope = Scope(tmp_path)
    first = scope.seal("first", FOUR)
    second = scope.seal("second", {"a.txt": b"a.txt", "e.txt": b"e"})
    events, store = InMemoryKeptEvents(), Counting()

    PyposlibKeeping(events, store).append(LEDGER, *first, {}, "who")
    PyposlibKeeping(events, store).append(LEDGER, *second, {}, "who")

    shared = BLOCKS + scope.cids()["first/a.txt"]
    assert scope.cids()["second/a.txt"] == scope.cids()["first/a.txt"]
    assert store.written.count(shared) == 1
    assert BLOCKS + scope.cids()["second/e.txt"] in store.written


def test_an_append_asks_no_question_twice(tmp_path: Path) -> None:
    name, data, files = Scope(tmp_path).seal("first", FOUR)
    events, store = InMemoryKeptEvents(), Counting()

    PyposlibKeeping(events, store).append(LEDGER, name, data, files, {}, "who")

    assert len(store.asked) == len(set(store.asked))
    assert sorted(store.asked) == sorted(store.written)


def test_a_block_that_cannot_be_written_keeps_no_event(tmp_path: Path) -> None:
    """The event's row is written after its blocks, so a store that
    fails part way leaves no event whose bytes are not held."""
    scope = Scope(tmp_path)
    name, data, files = scope.seal("first", FOUR)
    unwritable = BLOCKS + scope.cids()["first/c.txt"]

    class Failing(InMemoryObjectStore):
        def put(
            self,
            key: str,
            body: bytes,
            content_type: str = "application/json",
            content_encoding: str | None = "gzip",
        ) -> None:
            if key == unwritable:
                raise ObjectStoreError(f"could not write {key}")
            super().put(key, body, content_type, content_encoding)

    events = InMemoryKeptEvents()

    with pytest.raises(ObjectStoreError):
        PyposlibKeeping(events, Failing()).append(
            LEDGER, name, data, files, {}, "who"
        )

    assert events.of_ledger(LEDGER) == []
