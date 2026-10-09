"""The binding: the record that this server stores the archive of one ledger.

A ledger is identified by a UUID that every one of its events carries. The
id stays the same if the repository is renamed or moved, so the archive is
registered by ledger id and not by repository name. The binding also notes
which repository and scope the ledger belongs to.

Only an operator creates a binding. A client cannot register a ledger by
uploading to it. Otherwise anyone with commit access to a repository could
start a new ledger and have it stored as that repository's archive.
"""

import re
from dataclasses import dataclass

_LEDGER_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


@dataclass(frozen=True, kw_only=True)
class ArchiveBinding:
    #: The ledger's id: a lower-case UUID.
    ledger_id: str
    forge: str
    repo: str
    #: The path of the scope inside the repository, with "/" between
    #: parts. Empty for the repository's top level.
    scope: str = ""

    def __post_init__(self) -> None:
        if not _LEDGER_ID.fullmatch(self.ledger_id):
            raise ValueError(
                f"{self.ledger_id!r} is no ledger id: one is a UUID in "
                "lower case, as the ledger's events carry it"
            )
        parts = self.scope.split("/") if self.scope else []
        if "\\" in self.scope or any(p in ("", ".", "..") for p in parts):
            raise ValueError(
                f"{self.scope!r} is no scope: one is a path within the "
                "repository, or empty for its root"
            )
