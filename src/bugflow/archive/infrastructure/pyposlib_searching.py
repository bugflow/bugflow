"""Search over a stored archive, using an index.

The index is separate from the keeper. It finds out which files a ledger
has from the ledger's events, reads each file through the reading
interface, and stores the lines of the text files, by CID. The keeper is
not changed by any of this.

A search works out which files the ledger currently has, in the archive's
order, and asks the index for matching lines in those files. The index does
the matching, in the ``literal`` and ``regex`` modes. Everything else
follows pyposlib: which files are searched, how a file is named in a
result, the order of results and the refusals. So this server and
pyposlib's own search over the same archive on disk give the same results.

Keeping the index up to date needs no queue. The index remembers how many
of a ledger's events it has covered. A catch-up reads the events after
that. If another event arrives during a catch-up, the next catch-up picks
it up.
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

#: The search modes this index offers. The protocol's other modes rank their
#: results, and none of those is built yet.
MODES: tuple[str, ...] = ("literal", "regex")


@dataclass(frozen=True)
class _Layout:
    """What a ledger's events say about its files: the entry for each path,
    the CID of each path, and the items and collections, which are used to
    name a file in a result.
    """

    events: int
    erased: frozenset[str]
    entries: dict[str, Any]
    cids: dict[str, str]
    items: list[str]
    collections: set[str]

    def paths(self, chosen: Callable[[str], bool]) -> list[str]:
        """The paths of the ledger's files, in the archive's order, leaving
        out any with no CID, any whose bytes were deleted on request, and
        any that ``chosen`` rejects.
        """
        return [
            path
            for path in searching.by_path(self.entries)
            if path in self.cids
            and self.cids[path] not in self.erased
            and chosen(path)
        ]


def _name_of(number: int, data: bytes) -> str:
    """Work out the file name of event ``number`` from its bytes.

    The protocol's "event" operation returns only the bytes. The name is
    the number followed by a hash of the bytes (or their CID, for a schema
    3 event), so it can be rebuilt.
    """
    recorded = json.loads(data)
    schema = recorded.get("schema") if isinstance(recorded, dict) else None
    named = (
        archive_integrity.event_cid(data)
        if schema == 3
        else archive_integrity.sha(data)
    )
    return f"{number:08d}-{named}.json"


def _lines(data: bytes) -> tuple[str, ...] | None:
    """Split a file's bytes into lines, or return None if the file is not
    text. A file is not text if it is not valid UTF-8, or if it contains a
    NUL character, which a database text column cannot store.
    """
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
            # An old ledger whose events record no CIDs has no archive CIDs to
            # work out, so there is nothing a result could refer to.
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
            # If an event arrived while this pass was running, the loop goes
            # round again for it.
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
