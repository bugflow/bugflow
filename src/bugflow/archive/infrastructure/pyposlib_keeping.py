"""The keeping side of the protocol, by the sealing library's keeper.

pyposlib's ``Keeper`` verifies what a client sends as the remote archive
protocol requires. Here it is given what this server holds: a ledger's
events from their repository, and the object store as the mapping its
blocks live in. So the rules a seal is held to are the library's, kept
in lockstep with the client that seals, and nothing of them is written
here.

A keeper is made for each call, over the events as they are then. The
blocks an event needs are written once the keeper has verified it and
before the event's row is: a failure between the two leaves blocks no
ledger enrols, which are harmless, and never an event whose bytes are
not held. Under version 2 a client puts the blocks first, each written
once the keeper has verified it hashes to its CID, and the event is
appended alone; the keeper then reads each entry's blocks from the
store to see that every one is held.

Which versions this keeper serves, and any it is retiring, are given
to it; the libraries' keeper lists them in describe and refuses what a
version it does not serve would allow.

The object store may be far from this host, and a call to it then costs
a round trip. An event of a thousand files asked after and written one
at a time took longer than a sealing client waits. So the questions an
append will put to the store are asked together beforehand, and what
the keeper assigns is held and written together afterwards, several
calls at once.
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

#: Where a block is kept in the object store, by its CID. Blocks are
#: kept once however many ledgers enrol them.
BLOCKS = "archive/blocks/"


#: How many calls to the object store are in flight at once for one
#: append. Below the ten connections an S3 client keeps by default.
AT_ONCE = 8


class _Blocks:
    """The object store as the mapping a keeper keeps blocks in, for one
    call: it asks whether a block is held, reads one, and assigns one.

    What is assigned is held here until ``write`` puts it in the store,
    so that nothing of an append the keeper refuses is written. Whether
    a block is held is asked of the store once and remembered; ``ask``
    asks after many together.
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
            # Consumed, so that a call that failed raises here.
            list(pool.map(operation, cids))

    def ask(self, cids: Iterable[str]) -> None:
        """Learn whether each of ``cids`` is held, asking the store after
        several at once. A CID left out is asked after when the keeper
        asks: leaving one out costs time and changes no answer."""

        def learn(cid: str) -> None:
            held = self._store.has(BLOCKS + cid)
            self._held[cid] = held

        self._together(learn, sorted(set(cids) - self._held.keys()))

    def write(self) -> None:
        """Put in the store each block assigned that it does not hold,
        several at once. A block is kept once however many ledgers enrol
        it."""
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
        """The block, or ``default`` where none is held: what a mapping
        answers, which the keeper asks when it walks a file's blocks."""
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
    """The CIDs a keeper holding ``kept`` asks its blocks after when it
    is sent the event ``data`` with the files ``sent``: those the event
    enrols if the ledger was of schema 3 before it, and otherwise every
    one the ledger then enrols, since that event is where a keeper
    requires them all.

    A guess made to ask early, and nothing the keeper goes by: an event
    it will refuse gives no CIDs here, and the keeper says why.
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
    """What the operation returns, its refusal carried as this
    context's. Bytes that are not JSON at all are an encoding fault."""
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
    """The number an event file's name gives it, or None for a name
    that is no event file's."""
    named = archive_integrity.EVENT_NAME.fullmatch(name)
    return int(named[1]) if named else None


class PyposlibKeeping:
    """The library's keeper over this server's storage. It is given no
    search modes: the keeper reads nothing it keeps, and search is
    answered beside it from an index."""

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
