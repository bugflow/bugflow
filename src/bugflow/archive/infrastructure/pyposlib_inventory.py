"""Works out a ledger's inventory from its stored events, using pyposlib. It
reads only the events, never the object store.
"""

import json

from pyposlib import archive_integrity
from pyposlib.archive_integrity import Refused

from bugflow.archive.domain.models.inventory import (
    ArchivedBundle,
    ArchivedFile,
    ArchiveInventory,
)
from bugflow.archive.domain.repositories.kept_events import (
    KeptEventRepository,
)
from bugflow.archive.infrastructure.pyposlib_keeping import _refusing


class PyposlibInventory:
    def __init__(self, events: KeptEventRepository) -> None:
        self._events = events

    def inventory(self, ledger_id: str) -> ArchiveInventory:
        events = self._events.of_ledger(ledger_id)
        entries, _, _, _, _, empty = _refusing(
            lambda: archive_integrity.chain(
                [(event.name, event.data) for event in events]
            )
        )
        files = {
            path: ArchivedFile(
                path=path, size=entry["size"], cid=entry.get("cid")
            )
            for path, entry in sorted(entries.items())
        }
        owners: dict[str, int] = {}
        labels: dict[int, str] = {}
        for event in events:
            recorded = json.loads(event.data)
            if recorded.get("kind") == "conversion":
                removed = recorded.get("remove", [])
                renamed = recorded.get("rename", {})
                owners = {
                    renamed.get(path, path): number
                    for path, number in owners.items()
                    if path not in removed
                }
                if not recorded.get("add"):
                    continue
            labels[event.number] = recorded.get(
                "item", f"Record {event.number}"
            )
            for path in recorded.get("add", {}):
                owners[path] = event.number
        bundles = tuple(
            ArchivedBundle(
                number=number,
                item=item,
                files=tuple(
                    file
                    for path, file in files.items()
                    if owners.get(path) == number
                ),
            )
            for number, item in labels.items()
        )
        try:
            folded = dict(archive_integrity.fold(entries, empty))
        except Refused:
            # An old ledger whose events record no CIDs has no archive CIDs to
            # work out, so no reference can point into it.
            folded = {}
        return ArchiveInventory(
            events=len(events),
            files=tuple(files.values()),
            bundles=bundles,
            folded=folded,
        )
