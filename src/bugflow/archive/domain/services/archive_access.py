"""Interface: whether a caller may read a ledger's archive, or append
to it.

Who a caller is and which roles they hold is the identity provider's to
say; which ledgers a caller may reach is this server's. It is an
interface because how that is decided ledger by ledger is not settled.
"""

from typing import Protocol

from bugflow.shared.domain.values.caller import Caller


class ArchiveAccessService(Protocol):
    def may_read(self, caller: Caller, ledger_id: str) -> bool:
        """Whether ``caller`` may read what is kept of the ledger."""
        ...

    def may_append(self, caller: Caller, ledger_id: str) -> bool:
        """Whether ``caller`` may append an event to the ledger."""
        ...
