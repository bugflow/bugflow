"""An event is kept only once the sealing library's keeper has verified
it, over this server's own storage.

The events are real: each test seals into a scope on disk with pyposlib,
as a client does, and sends what the seal wrote. The object store is the
in-memory one, which refuses a key written twice, so a block kept once
is also a test here.
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from pyposlib import archive_integrity, cid

from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.domain.models.kept_event import KeptEvent
from bugflow.archive.domain.repositories.kept_events import EventTakenError
from bugflow.archive.infrastructure.in_memory_kept_events import (
    InMemoryKeptEvents,
)
from bugflow.archive.infrastructure.pyposlib_keeping import (
    BLOCKS,
    PyposlibKeeping,
)
from bugflow.archive.tests.sealed_scope import LEDGER, Scope
from bugflow.shared.infrastructure.in_memory_object_store import (
    InMemoryObjectStore,
)

OTHER = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
SHARDED = Path(__file__).parent / "fixtures/past-sharding-threshold.json"


def kept() -> tuple[PyposlibKeeping, InMemoryKeptEvents, InMemoryObjectStore]:
    events, store = InMemoryKeptEvents(), InMemoryObjectStore()
    return PyposlibKeeping(events, store), events, store


def refused(operation: object) -> str:
    assert callable(operation)
    with pytest.raises(ArchiveRefusedError) as refusal:
        operation()
    return refusal.value.kind


def test_a_sealed_item_is_kept_with_its_claims_and_who_appended_it(
    tmp_path: Path,
) -> None:
    scope = Scope(tmp_path)
    name, data, files = scope.seal("first", {"a.txt": b"first"})
    keeping, events, store = kept()

    answer = keeping.append(
        LEDGER, name, data, files, {"head": "abc"}, "someone"
    )

    head, root = scope.head_and_root()
    assert answer.appended
    assert (answer.description.head, answer.description.root) == (head, root)
    assert events.of_ledger(LEDGER) == [
        KeptEvent(
            ledger_id=LEDGER,
            number=1,
            name=name,
            data=data,
            claims={"head": "abc"},
            caller="someone",
        )
    ]
    assert all(key.startswith(BLOCKS) for key in store.objects)
    assert store.objects[BLOCKS + scope.cids()["first/a.txt"]] == b"first"


def test_what_was_kept_is_read_back_by_a_keeper_made_later(
    tmp_path: Path,
) -> None:
    """Nothing is held between calls but the events and the store."""
    scope = Scope(tmp_path)
    first = scope.seal("first", {"a.txt": b"first"})
    second = scope.seal("second", {"sub/c.txt": b"c"})
    _, events, store = kept()
    PyposlibKeeping(events, store).append(LEDGER, *first, {}, "someone")
    PyposlibKeeping(events, store).append(LEDGER, *second, {}, "someone")
    later = PyposlibKeeping(events, store)
    cids = scope.cids()

    assert later.describe(LEDGER).events == 2
    assert later.event(LEDGER, 1) == first[1]
    assert later.read(LEDGER, cids["first/a.txt"], "") == b"first"
    assert later.read(LEDGER, cids["."], "second/sub/c.txt") == b"c"
    assert refused(lambda: later.event(LEDGER, 3)) == "absent"
    assert (
        refused(lambda: later.read(LEDGER, cids["."], "nowhere")) == "absent"
    )
    assert later.describe(OTHER).events == 0


def sharded_item() -> tuple[dict[str, bytes], str]:
    """The files of poslib's fixture of a directory IPFS shards, whose
    plain node would be a byte past the threshold, and the CID kubo
    recorded for it."""
    fixture = json.loads(SHARDED.read_text())
    files: dict[str, bytes] = {}
    for entry in fixture["tree"]:
        paths = (
            [entry["path"] % i for i in range(entry["series"])]
            if "series" in entry
            else [entry["path"]]
        )
        for path in paths:
            name = path.removeprefix(fixture["entry"] + "/")
            files[name] = entry["text"].encode()
    return files, fixture["cid"]


def test_an_item_whose_directory_shards_is_kept_with_its_shard_blocks(
    tmp_path: Path,
) -> None:
    """A directory whose plain node would pass 262144 bytes is a HAMT
    shard. The keeper folds the root the client sealed and keeps the
    block of every shard, the sub-shards included."""
    files, recorded = sharded_item()
    scope = Scope(tmp_path)
    sent = scope.seal("t", files)
    keeping, events, store = kept()

    answer = keeping.append(LEDGER, *sent, {}, "someone")

    cids = scope.cids()
    assert cids["t"] == recorded
    assert answer.appended
    assert answer.description.root == scope.head_and_root()[1]
    assert len(events.of_ledger(LEDGER)) == 1
    shards = [
        key
        for key, block in store.objects.items()
        # Only a dag-pb block, "bafybei" in base32, parses as a node; a
        # raw leaf or the dag-json event does not. A HAMT shard's data
        # begins with its UnixFS type, 5.
        if key.startswith(BLOCKS + "bafybei")
        and cid.parse(block)[1][:2] == b"\x08\x05"
    ]
    assert BLOCKS + cids["t"] in shards
    assert len(shards) > 1


def test_bytes_that_are_not_their_cid_s_keep_nothing(tmp_path: Path) -> None:
    name, data, files = Scope(tmp_path).seal("first", {"a.txt": b"first"})
    keeping, events, store = kept()

    kind = refused(
        lambda: keeping.append(
            LEDGER, name, data, {cid: b"other" for cid in files}, {}, "who"
        )
    )

    assert kind == "entry"
    assert events.of_ledger(LEDGER) == [] and store.objects == {}


def test_an_event_without_its_files_keeps_nothing(tmp_path: Path) -> None:
    name, data, _ = Scope(tmp_path).seal("first", {"a.txt": b"first"})
    keeping, events, store = kept()

    assert (
        refused(lambda: keeping.append(LEDGER, name, data, {}, {}, "who"))
        == "entry"
    )
    assert events.of_ledger(LEDGER) == [] and store.objects == {}


def test_another_ledger_s_event_is_refused(tmp_path: Path) -> None:
    sent = Scope(tmp_path, OTHER).seal("first", {"a.txt": b"first"})
    keeping, events, _ = kept()

    assert (
        refused(lambda: keeping.append(LEDGER, *sent, {}, "who")) == "identity"
    )
    assert events.of_ledger(LEDGER) == []


def begun(
    unnamed: int, ledger: str = LEDGER, text: str = "old"
) -> list[tuple[str, bytes]]:
    """The first events of a ledger begun before events carried a
    ledger_id: ``unnamed`` events that name no ledger, then one that
    names ``ledger``. ``text`` tells one such ledger from another."""
    events: list[tuple[str, bytes]] = []
    previous = None
    for number in range(1, unnamed + 2):
        data = f"{text} {number}".encode()
        value: dict[str, object] = {
            "schema": 1,
            "previous": previous,
            "add": {
                f"{number}.md": {
                    "mode": 0o444,
                    "sha256": archive_integrity.sha(data),
                    "size": len(data),
                }
            },
        }
        if number > unnamed:
            value["ledger_id"] = ledger
        event = archive_integrity.encoded(value)
        previous = archive_integrity.sha(event)
        events.append((f"{number:08}-{previous}.json", event))
    return events


def test_first_events_that_name_no_ledger_are_kept_with_those_after_them() -> (
    None
):
    """Each is sent with the events after it, up to the one that names
    the ledger, and is the only event kept of that append."""
    sent = begun(2)
    keeping, events, _ = kept()

    for number, (name, data) in enumerate(sent, 1):
        answer = keeping.append(
            LEDGER, name, data, {}, {}, "someone", sent[number:]
        )
        assert answer.appended
        assert answer.description.events == number

    assert [(e.name, e.data) for e in events.of_ledger(LEDGER)] == sent


@pytest.mark.parametrize(
    ("following", "kind"),
    [
        (lambda: [], "identity"),
        (lambda: begun(2)[1:2], "identity"),
        (lambda: begun(2, OTHER)[1:], "identity"),
        (lambda: begun(2, text="other")[1:], "chain"),
    ],
    ids=[
        "sent alone",
        "followed only by an event that names none",
        "followed to an event that names another ledger",
        "followed by another ledger's events",
    ],
)
def test_an_unnamed_event_keeps_nothing_unless_this_ledger_follows(
    following: Callable[[], list[tuple[str, bytes]]], kind: str
) -> None:
    name, data = begun(2)[0]
    keeping, events, store = kept()

    assert kind == refused(
        lambda: keeping.append(
            LEDGER, name, data, {}, {}, "someone", following()
        )
    )
    assert events.of_ledger(LEDGER) == []
    assert store.objects == {}


def test_bytes_that_are_no_event_are_an_encoding_fault() -> None:
    keeping, _, _ = kept()
    data = b"not json"
    name = f"00000001-{archive_integrity.sha(data)}.json"

    assert (
        refused(lambda: keeping.append(LEDGER, name, data, {}, {}, "who"))
        == "encoding"
    )


def test_the_same_event_again_changes_nothing(tmp_path: Path) -> None:
    sent = Scope(tmp_path).seal("first", {"a.txt": b"first"})
    keeping, events, _ = kept()
    first = keeping.append(LEDGER, *sent, {}, "who")

    again = keeping.append(LEDGER, *sent, {"said": "again"}, "another")

    assert not again.appended
    assert again.description == first.description
    assert [event.caller for event in events.of_ledger(LEDGER)] == ["who"]


def test_an_event_out_of_turn_is_refused_and_nothing_is_merged(
    tmp_path: Path,
) -> None:
    scope = Scope(tmp_path)
    scope.seal("first", {"a.txt": b"first"})
    second = scope.seal("second", {"b.txt": b"second"})
    keeping, events, _ = kept()

    assert (
        refused(lambda: keeping.append(LEDGER, *second, {}, "who")) == "chain"
    )
    assert events.of_ledger(LEDGER) == []


def test_a_block_two_items_share_is_kept_once(tmp_path: Path) -> None:
    """The in-memory store refuses a key written twice, so this passes
    only because the keeper asks before it writes."""
    scope = Scope(tmp_path)
    first = scope.seal("first", {"a.txt": b"same"})
    second = scope.seal("second", {"b.txt": b"same"})
    keeping, _, store = kept()

    keeping.append(LEDGER, *first, {}, "who")
    keeping.append(LEDGER, *second, {}, "who")

    cids = scope.cids()
    assert cids["first/a.txt"] == cids["second/b.txt"]
    assert keeping.read(LEDGER, cids["."], "second/b.txt") == b"same"
    assert store.objects[BLOCKS + cids["first/a.txt"]] == b"same"


def test_an_event_that_lost_the_race_for_its_number_is_refused(
    tmp_path: Path,
) -> None:
    """Two clients append at once: both verify against the same chain,
    and the row's primary key lets one in."""

    class Raced(InMemoryKeptEvents):
        def add(self, event: KeptEvent) -> None:
            raise EventTakenError("another got there")

    sent = Scope(tmp_path).seal("first", {"a.txt": b"first"})
    keeping = PyposlibKeeping(Raced(), InMemoryObjectStore())

    assert refused(lambda: keeping.append(LEDGER, *sent, {}, "who")) == "chain"
