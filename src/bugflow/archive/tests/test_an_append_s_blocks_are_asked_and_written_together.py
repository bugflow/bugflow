"""Tests that an append talks to the object store several calls at a time, not
one by one.

The object store may be on another machine, so each call takes time. One
call at a time for a thousand files took longer than a client waits.

The tests use two fake stores to show this without a network. ``Counting``
counts the calls. ``Together`` blocks a call until several are waiting at
once, so code that makes its calls one at a time gets stuck and the test
fails.
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
    """An object store that counts how often each key is asked about and
    written.
    """

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
    """An object store that lets a call through only when ``parties`` calls
    are waiting at the same time. Code that makes one call at a time never
    gets through, and the test fails with a broken barrier.
    """

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
    """An event may refer to a file the store already has, sent without the
    file's bytes. The keeper then has to ask the store whether it has it.
    Here a second ledger adds the first ledger's files that way, and the
    questions must go several at once.
    """
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
    """Two items containing the same file share one block. The second append
    finds the block already stored and does not write it again.
    """
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
    """If writing a block fails, the event is not stored. Blocks are written
    before the event, so there is never a stored event whose files are
    missing.
    """
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
