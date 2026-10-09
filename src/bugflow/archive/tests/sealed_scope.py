"""A test helper that produces real archive events.

It makes a scope in a temporary directory and seals files into it with
pyposlib, exactly as a sealing tool does. Each seal writes a real event.
The tests send those events to the code under test, so what is tested is
what a real client sends.
"""

import json
from pathlib import Path

from pyposlib import archive_integrity, seal

LEDGER = "0f1e2d3c-4b5a-4968-8778-a6b5c4d3e2f1"

#: What a client sends in one append: the event's file name, the event's bytes,
#: and the files it adds, by CID.
Sent = tuple[str, bytes, dict[str, bytes]]


class Scope:
    def __init__(self, root: Path, ledger: str = LEDGER) -> None:
        self.scope = root / "scope"
        self.archive = self.scope / "archives"
        self.archive.mkdir(parents=True)
        self.ledger = ledger

    def seal(self, item: str, files: dict[str, bytes]) -> Sent:
        """Seal ``files`` into the scope as one item. Return what a client
        would send for it: the event's file name, its bytes, and the files
        by CID.
        """
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
        """The CID of every file and directory sealed so far. The archive's
        top level is ".".
        """
        return dict(archive_integrity.fold_cids(self.archive))

    def head_and_root(self) -> tuple[str, str]:
        history = archive_integrity.history(self.archive)
        return history[1], history[4]
