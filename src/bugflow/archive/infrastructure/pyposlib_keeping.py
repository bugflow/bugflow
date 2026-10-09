"""The keeper, built on pyposlib's own ``Keeper`` class.

pyposlib's ``Keeper`` contains the protocol's rules for checking what a
client sends. This module does not repeat them. It gives ``Keeper`` this
server's storage: a ledger's events from the events repository, and the
object store, wrapped to look like the dictionary of blocks that ``Keeper``
expects. The sealing tools use the same library, so client and server apply
the same rules.

A new ``Keeper`` is created for each call, from the events stored at that
moment.

Order of writing. For an append, the blocks are written to the object store
first, after ``Keeper`` has accepted the event, and the event's row is
written last. If something fails in between, some blocks are stored that no
event refers to, which does no harm. The opposite, an event stored without
its files, cannot happen.

Protocol version 2. The client uploads blocks before the event. Each block
is written once ``Keeper`` has confirmed it hashes to its CID. The event
then arrives on its own, and ``Keeper`` checks that every block it needs is
in the store.

Speed. The object store may be on another machine, so each call to it takes
time. Checking and writing a thousand files one call at a time took longer
than a client waits for an answer. So an append first asks the store about
all the blocks it will need, several calls at once, and afterwards writes
the new blocks the same way.
"""

import json
from collections.abc import (
    Callable,
    Collection,
    Iterable,
    Mapping,
    Sequence,
)
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pyposlib import archive_integrity, remote
from pyposlib.archive_integrity import Refused

from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.domain.models.description import Appended, Description
from bugflow.archive.domain.models.kept_event import KeptEvent
from bugflow.archive.domain.repositories.kept_events import (
    EventTakenError,
    KeptEventRepository,
)
from bugflow.shared.domain.services.object_store import ObjectStoreService

#: The start of a block's key in the object store. The CID follows. A block is
#: stored once, however many ledgers refer to it.
BLOCKS = "archive/blocks/"


#: How many calls to the object store one append makes at the same time. An S3
#: client keeps ten connections by default, so this stays below ten.
AT_ONCE = 8


class _Blocks:
    """The object store, wrapped as the dictionary of blocks that pyposlib's
    ``Keeper`` expects. One is made for each call.

    ``Keeper`` uses it in three ways: ``cid in blocks``, ``blocks[cid]``
    and ``blocks[cid] = data``.

    Assignments are not written to the store at once. They are held here
    until ``write`` is called, so that if ``Keeper`` refuses the append,
    nothing has been written.

    Whether the store has a block is asked once and remembered. ``ask``
    asks about many blocks at the same time.
    """

    def __init__(self, store: ObjectStoreService) -> None:
        self._store = store
        self._held: dict[str, bool] = {}
        self._assigned: dict[str, bytes] = {}

    def _is_held(self, cid: str) -> bool:
        if cid not in self._held:
            self._held[cid] = self._store.has(BLOCKS + cid)
        return self._held[cid]

    def _together(
        self, operation: Callable[[str], None], cids: list[str]
    ) -> None:
        if not cids:
            return
        with ThreadPoolExecutor(max_workers=AT_ONCE) as pool:
            # Read all the results, so that an error in any call is raised
            # here.
            list(pool.map(operation, cids))

    def ask(self, cids: Iterable[str]) -> None:
        """Find out whether the store has each of ``cids``, several calls at
        once, and remember the answers. This is only to save time: a CID
        not asked about here is asked about later, when ``Keeper`` needs
        it.
        """

        def learn(cid: str) -> None:
            held = self._store.has(BLOCKS + cid)
            self._held[cid] = held

        self._together(learn, sorted(set(cids) - self._held.keys()))

    def write(self) -> None:
        """Write to the store every block that was assigned and that the store
        does not already have, several calls at once.
        """
        self.ask(self._assigned)

        def put(cid: str) -> None:
            self._store.put(
                BLOCKS + cid,
                self._assigned[cid],
                "application/octet-stream",
                None,
            )
            self._held[cid] = True

        self._together(
            put, sorted(cid for cid in self._assigned if not self._held[cid])
        )
        self._assigned.clear()

    def __contains__(self, cid: object) -> bool:
        return isinstance(cid, str) and (
            cid in self._assigned or self._is_held(cid)
        )

    def __getitem__(self, cid: str) -> bytes:
        if cid in self._assigned:
            return self._assigned[cid]
        found = self._store.get(BLOCKS + cid)
        if found is None:
            raise KeyError(cid)
        return found

    def get(self, cid: str, default: bytes | None = None) -> bytes | None:
        """Return the block, or ``default`` if there is none, as ``dict.get``
        does. ``Keeper`` calls this when it follows a file's blocks.
        """
        try:
            return self[cid]
        except KeyError:
            return default

    def __setitem__(self, cid: str, block: bytes) -> None:
        self._assigned.setdefault(cid, block)


def _asked_after(
    kept: list[tuple[str, bytes]],
    name: str,
    data: bytes,
    sent: Collection[str],
) -> set[str]:
    """Predict which CIDs ``Keeper`` will look up while checking this event,
    so they can all be asked about beforehand.

    If the ledger was already in the current format (schema 3), it is the
    files this event adds. If this is the ledger's first schema 3 event, it
    is every file the ledger refers to, because that is the point where the
    keeper requires them all.

    This is only a prediction to save time. ``Keeper`` does the real check.
    For an event that will be refused, this returns nothing.
    """
    try:
        recorded = json.loads(data)
        if recorded.get("schema") != 3:
            return set()
        entries = archive_integrity.chain([*kept, (name, data)])[0]
        last = (
            archive_integrity.EVENT_NAME.fullmatch(kept[-1][0])
            if kept
            else None
        )
        already = last is not None and archive_integrity.is_event_cid(last[2])
        paths = recorded.get("add", {}) if already else entries
        return {
            entries[path]["cid"] for path in paths if path in entries
        } - set(sent)
    except (Refused, ValueError, KeyError, TypeError, AttributeError):
        return set()


def _refusing[T](operation: Callable[[], T]) -> T:
    """Run ``operation``. Turn a refusal from pyposlib into this context's
    ``ArchiveRefusedError``. Bytes that are not JSON at all are refused as
    "encoding".
    """
    try:
        return operation()
    except Refused as refused:
        raise ArchiveRefusedError(refused.kind, str(refused)) from refused
    except json.JSONDecodeError as exc:
        raise ArchiveRefusedError("encoding", "Not an event") from exc


def _description(ledger_id: str, described: Mapping[str, Any]) -> Description:
    return Description(
        ledger_id=ledger_id,
        head=described["head"],
        events=described["events"],
        root=described["root"],
        erased=tuple(described["erased"]),
        protocols=tuple(described.get("protocols") or [described["protocol"]]),
        retiring=tuple(
            (int(version), date)
            for version, date in sorted(described.get("retiring", {}).items())
        ),
    )


def _number(name: str) -> int | None:
    """The number at the start of an event file's name, or None if the name is
    not an event file's.
    """
    named = archive_integrity.EVENT_NAME.fullmatch(name)
    return int(named[1]) if named else None


class PyposlibKeeping:
    """The keeper: pyposlib's ``Keeper`` over this server's events and object
    store.

    It is created with no search modes. Search is handled separately, from
    an index (see ``pyposlib_searching.py``).
    """

    def __init__(
        self,
        events: KeptEventRepository,
        store: ObjectStoreService,
        protocols: Sequence[int] = remote.VERSIONS,
        retiring: Mapping[int, str] | None = None,
    ) -> None:
        self._events = events
        self._store = store
        self._protocols = tuple(protocols)
        self._retiring = dict(retiring or {})

    def _kept(self, ledger_id: str) -> list[tuple[str, bytes]]:
        return [
            (event.name, event.data)
            for event in self._events.of_ledger(ledger_id)
        ]

    def _keeper(self, ledger_id: str, blocks: _Blocks | None = None) -> Any:
        return remote.Keeper(
            ledger_id,
            self._kept(ledger_id),
            blocks if blocks is not None else _Blocks(self._store),
            protocols=self._protocols,
            retiring=self._retiring,
            modes=(),
        )

    def describe(self, ledger_id: str) -> Description:
        keeper = self._keeper(ledger_id)
        return _description(ledger_id, _refusing(keeper.describe))

    def event(self, ledger_id: str, number: int) -> bytes:
        keeper = self._keeper(ledger_id)
        return bytes(_refusing(lambda: keeper.event(number)))

    def held(self, ledger_id: str, cids: Sequence[str]) -> list[str]:
        blocks = _Blocks(self._store)
        keeper = self._keeper(ledger_id, blocks)
        blocks.ask(cids)
        return list(_refusing(lambda: keeper.held(list(cids))))

    def put(self, ledger_id: str, cid: str, data: bytes) -> bool:
        blocks = _Blocks(self._store)
        keeper = self._keeper(ledger_id, blocks)
        new = bool(_refusing(lambda: keeper.put(cid, data)))
        blocks.write()
        return new

    def append(
        self,
        ledger_id: str,
        name: str,
        data: bytes,
        files: Mapping[str, bytes],
        claims: Mapping[str, str],
        caller: str,
        following: Sequence[tuple[str, bytes]] = (),
    ) -> Appended:
        kept = self._kept(ledger_id)
        blocks = _Blocks(self._store)
        keeper = remote.Keeper(
            ledger_id,
            kept,
            blocks,
            protocols=self._protocols,
            retiring=self._retiring,
            modes=(),
        )
        before = len(kept)
        if _number(name) == before + 1:
            blocks.ask(_asked_after(kept, name, data, files))
        described = _refusing(
            lambda: keeper.append(
                name, data, dict(files), dict(claims), list(following)
            )
        )
        appended = described["events"] > before
        if appended:
            blocks.write()
            try:
                self._events.add(
                    KeptEvent(
                        ledger_id=ledger_id,
                        number=before + 1,
                        name=name,
                        data=data,
                        claims=dict(claims),
                        caller=caller,
                    )
                )
            except EventTakenError as taken:
                raise ArchiveRefusedError(
                    "chain", f"Another event is number {before + 1}"
                ) from taken
        return Appended(
            description=_description(ledger_id, described), appended=appended
        )

    def read(self, ledger_id: str, cid: str, path: str) -> bytes:
        keeper = self._keeper(ledger_id)
        return bytes(_refusing(lambda: keeper.read(cid, path)))
