"""Whose archive this server keeps, and for which repository.

A scope's archive is known by its ledger: every event of a ledger
carries one id, which stays when the repository is renamed or moves.
A binding says that this server keeps the archive of that ledger, for
a scope of a repository. Only an operator makes one, so
that nobody with a repository's commit access alone can have a
different archive kept in a scope's name.
"""

import re
from dataclasses import dataclass

_LEDGER_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


@dataclass(frozen=True, kw_only=True)
class ArchiveBinding:
    #: The ledger's id, a UUID in canonical lower-case form, as every
    #: event of the ledger carries it.
    ledger_id: str
    forge: str
    repo: str
    #: The scope's path within the repository, "/"-separated, and empty
    #: for the repository's own root scope.
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
