"""Searching a kept archive beside its keeper, by the sealing library's
rules.

An indexer that is a client of the archive protocol: it learns the
files a ledger enrols from the ledger's events, reads each through
read, and keeps the lines of those that are text by CID, in an index
apart from the keeper's store. The keeper verifies and stores as
before and reads nothing it keeps.

A search asks the index for the files the ledger's fold names, in the
archive's order, and answers hits as section 12 of poslib's
``doc/remote-archive-protocol.txt`` has them. The matching is the
index's, in ``literal`` and ``regex``; which files are searched, how a
file is named in a hit, the order and the refusals are pyposlib's, so
this host and the library's own adapter over the same archive on disk
answer the same hits.

The ledger is the queue. What the index has read of a ledger is a count
of events; a catch-up reads the events after it, and an append of
another event meanwhile is read by the next.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pyposlib import archive_integrity
from pyposlib import search as searching
from pyposlib.archive_integrity import Refused

from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.domain.models.index_position import CaughtUp
from bugflow.archive.domain.models.indexed_file import IndexedFile
from bugflow.archive.domain.models.search_hit import SearchHit
from bugflow.archive.domain.repositories.index_positions import (
    IndexPositionRepository,
)
from bugflow.archive.domain.repositories.indexed_files import (
    IndexedFileRepository,
)
from bugflow.archive.domain.services.reading import ArchiveReadingService
from bugflow.archive.infrastructure.pyposlib_keeping import _refusing

#: The modes the index answers. Every other is a ranked mode, and none
#: is built yet.
MODES: tuple[str, ...] = ("literal", "regex")


@dataclass(frozen=True)
class _Layout:
    """What a ledger's events say of its files: the entries, what each
    path folds to, and the items and collections a hit is named by."""

    events: int
    erased: frozenset[str]
    entries: dict[str, Any]
    cids: dict[str, str]
    items: list[str]
    collections: set[str]

    def paths(self, chosen: Callable[[str], bool]) -> list[str]:
        """The enrolled files, in the archive's order, that fold to a CID,
        are not erased, and ``chosen`` takes."""
        return [
            path
            for path in searching.by_path(self.entries)
            if path in self.cids
            and self.cids[path] not in self.erased
            and chosen(path)
        ]


def _name_of(number: int, data: bytes) -> str:
    """The ledger file's name for event ``number`` of bytes ``data``: the
    protocol's event gives the bytes alone, and the chain checks the name
    against them, so the name is the bytes' own."""
    recorded = json.loads(data)
    schema = recorded.get("schema") if isinstance(recorded, dict) else None
    named = (
        archive_integrity.event_cid(data)
        if schema == 3
        else archive_integrity.sha(data)
    )
    return f"{number:08d}-{named}.json"


def _lines(data: bytes) -> tuple[str, ...] | None:
    """The file's lines as the protocol counts them, or None for a file
    that is not text: not UTF-8, or holding a NUL, which no text store
    keeps."""
    lines = searching.lines_of(data)
    if lines is None or any("\x00" in line for line in lines):
        return None
    return tuple(lines)


def _everything(path: str) -> bool:
    return True


class PyposlibSearching:
    def __init__(
        self,
        reading: ArchiveReadingService,
        files: IndexedFileRepository,
        positions: IndexPositionRepository,
        modes: tuple[str, ...] = MODES,
    ) -> None:
        self._reading = reading
        self._files = files
        self._positions = positions
        unknown = [mode for mode in modes if mode not in MODES]
        if "literal" not in modes or unknown:
            raise ValueError(
                f"the index searches in {list(MODES)}, literal always, "
                f"not {list(modes)}"
            )
        self._modes = tuple(modes)

    @property
    def modes(self) -> tuple[str, ...]:
        return self._modes

    def _layout(
        self, ledger_id: str, events: int, erased: tuple[str, ...]
    ) -> _Layout:
        read = [
            (
                _name_of(number, data),
                data,
            )
            for number in range(1, events + 1)
            for data in [self._reading.event(ledger_id, number)]
        ]
        entries, _, _, collections, items, empty = _refusing(
            lambda: archive_integrity.chain(read)
        )
        try:
            cids = dict(archive_integrity.fold(entries, empty))
        except Refused:
            # A ledger still of a schema that enrols no CIDs folds to
            # nothing, and has nothing a hit could name.
            cids = {}
        return _Layout(
            events=events,
            erased=frozenset(erased),
            entries=dict(entries),
            cids=cids,
            items=list(items),
            collections=set(collections),
        )

    def catch_up(self, ledger_id: str) -> CaughtUp:
        files = 0
        described = self._reading.describe(ledger_id)
        while described.events > self._positions.position(ledger_id):
            layout = self._layout(
                ledger_id, described.events, described.erased
            )
            wanted: list[str] = []
            for path in layout.paths(_everything):
                cid = layout.cids[path]
                if cid not in wanted:
                    wanted.append(cid)
            held = self._files.indexed(wanted)
            for cid in wanted:
                if cid in held:
                    continue
                data = self._reading.read(ledger_id, cid, "")
                self._files.keep(IndexedFile(cid=cid, lines=_lines(data)))
                files += 1
            self._positions.advance(ledger_id, described.events)
            # An event appended while this read is the next pass's.
            described = self._reading.describe(ledger_id)
        return CaughtUp(
            ledger_id=ledger_id, events=described.events, files=files
        )

    def search(
        self,
        ledger_id: str,
        query: str,
        mode: str | None = None,
        limit: int | None = None,
        within: str | None = None,
    ) -> list[SearchHit]:
        if not query:
            raise ArchiveRefusedError("request", "Expected q, the query")
        chosen_mode = "literal" if mode is None else mode
        if chosen_mode not in self.modes:
            raise ArchiveRefusedError(
                "mode",
                f"Not a mode this keeper searches in, {list(self.modes)}: "
                f"{chosen_mode}",
            )
        if limit is None:
            limit = int(searching.LIMIT)
        elif limit < 1:
            raise ArchiveRefusedError(
                "request", f"limit is a positive integer: {limit!r}"
            )
        described = self._reading.describe(ledger_id)
        layout = self._layout(ledger_id, described.events, described.erased)
        chosen: Callable[[str], bool] = (
            _refusing(lambda: searching.beneath(layout.cids, within))
            if within is not None
            else _everything
        )
        paths = layout.paths(chosen)
        refs = [
            searching.reference(
                path, layout.cids, layout.items, layout.collections
            )
            for path in paths
        ]
        found = self._files.find(
            [layout.cids[path] for path in paths], query, chosen_mode, limit
        )
        return [
            SearchHit(
                ref=refs[line.position],
                first_line=line.number,
                last_line=line.number,
                passage=line.text,
            )
            for line in found
        ]
