"""The interface that decides whether a caller may read or append to a ledger.

The identity provider says who a caller is and which roles they have. This
server decides what those roles allow. The decision is behind an interface
so that it can change, for example to give access ledger by ledger.
"""

from typing import Protocol

from bugflow.shared.domain.values.caller import Caller


class ArchiveAccessService(Protocol):
    def may_read(self, caller: Caller, ledger_id: str) -> bool:
        """Whether ``caller`` may read the ledger."""
        ...

    def may_append(self, caller: Caller, ledger_id: str) -> bool:
        """Whether ``caller`` may add an event to the ledger."""
        ...
