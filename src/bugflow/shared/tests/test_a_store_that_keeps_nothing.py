"""Tests of the object store used when none is set up: it keeps nothing
and says so, without raising."""

from bugflow.shared.infrastructure.null_object_store import NullObjectStore


def test_a_store_that_keeps_nothing_has_nothing() -> None:
    store = NullObjectStore()
    store.put("a/key", b"some bytes")
    assert (store.get("a/key"), store.has("a/key")) == (None, False)
    assert store.configured is False
