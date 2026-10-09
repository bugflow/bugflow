"""Tests of ``archive_workings``: a run's workings are stored under the
hash of their bytes, and failing to store them returns an empty
reference."""

import gzip
import hashlib
import json

from bugflow.shared.domain.errors import ObjectStoreError
from bugflow.shared.infrastructure.in_memory_object_store import (
    InMemoryObjectStore,
)
from bugflow.work.infrastructure.workings import WORKINGS, archive_workings

EVENTS = [{"type": "message", "text": "read the files"}, {"type": "idle"}]


class NoStore(InMemoryObjectStore):
    """Stands for an application with no object store set up."""

    @property
    def configured(self) -> bool:
        return False


class RefusingStore(InMemoryObjectStore):
    """A store that cannot be written to."""

    def put(
        self,
        key: str,
        body: bytes,
        content_type: str = "application/json",
        content_encoding: str | None = "gzip",
    ) -> None:
        raise ObjectStoreError("the bucket refused the write")


def test_the_reference_is_the_hash_of_the_stored_bytes() -> None:
    store = InMemoryObjectStore()

    reference = archive_workings(store, EVENTS)

    (key,) = store.objects
    assert key == f"{WORKINGS}/{reference}.json.gz"
    assert reference == hashlib.sha256(store.objects[key]).hexdigest()
    assert json.loads(gzip.decompress(store.objects[key])) == EVENTS


def test_the_same_workings_stored_twice_are_one_object() -> None:
    store = InMemoryObjectStore()

    first = archive_workings(store, EVENTS)
    second = archive_workings(store, list(EVENTS))

    assert first == second
    assert len(store.objects) == 1


def test_with_no_store_set_up_nothing_is_stored() -> None:
    store = NoStore()

    assert archive_workings(store, EVENTS) == ""
    assert archive_workings(None, EVENTS) == ""
    assert store.objects == {}


def test_a_store_that_refuses_gives_an_empty_reference() -> None:
    assert archive_workings(RefusingStore(), EVENTS) == ""


def test_no_events_are_not_stored() -> None:
    store = InMemoryObjectStore()

    assert archive_workings(store, []) == ""
    assert store.objects == {}
