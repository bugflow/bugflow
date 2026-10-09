"""A scope on disk whose seals give real events to send to a keeper.

The tests of the archive context send what a client sends: each seals
an item into a scope with pyposlib, as a client does, and takes the
event the seal wrote and the files it enrolled.
"""

import json
from pathlib import Path

from pyposlib import archive_integrity, seal

LEDGER = "0f1e2d3c-4b5a-4968-8778-a6b5c4d3e2f1"

#: What an append sends: the ledger file's name, its bytes, and the
#: files it enrols by their CIDs.
Sent = tuple[str, bytes, dict[str, bytes]]


class Scope:
    def __init__(self, root: Path, ledger: str = LEDGER) -> None:
        self.scope = root / "scope"
        self.archive = self.scope / "archives"
        self.archive.mkdir(parents=True)
        self.ledger = ledger

    def seal(self, item: str, files: dict[str, bytes]) -> Sent:
        """Seal an item of those files; what its event's append sends."""
        for path, data in files.items():
            target = self.scope / item / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        plan = seal.plan(self.scope / item, self.archive / item, self.ledger)
        event, _ = seal.apply(
            plan, archive_integrity.sha(archive_integrity.encoded(plan))
        )
        data = event.read_bytes()
        added = json.loads(data)["add"]
        return (
            event.name,
            data,
            {
                entry["cid"]: (self.archive / path).read_bytes()
                for path, entry in added.items()
            },
        )

    def cids(self) -> dict[str, str]:
        """The CID of every file and directory sealed, the root as "."."""
        return dict(archive_integrity.fold_cids(self.archive))

    def head_and_root(self) -> tuple[str, str]:
        history = archive_integrity.history(self.archive)
        return history[1], history[4]
