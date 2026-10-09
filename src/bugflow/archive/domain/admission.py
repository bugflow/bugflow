"""Who is let through to a kept ledger, and what they are told if not.

Access is asked before the binding, so that a caller with no role is
refused the same way whether a ledger is kept here or not, and learns
nothing of which are. A ledger nobody bound is absent to everyone:
this server keeps an archive only where an operator said so.
"""

from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.archive.domain.repositories.bindings import BindingRepository
from bugflow.archive.domain.services.archive_access import (
    ArchiveAccessService,
)
from bugflow.shared.domain.values.caller import Caller


def admitted(
    allowed: bool, bindings: BindingRepository, ledger_id: str
) -> ArchiveBinding:
    """The ledger's binding, for a caller who is ``allowed``. Refused as
    access otherwise, and as absent for a ledger that is not bound."""
    if not allowed:
        raise ArchiveRefusedError("access", "Not allowed")
    binding = bindings.for_ledger(ledger_id)
    if binding is None:
        raise ArchiveRefusedError("absent", f"No ledger {ledger_id} is kept")
    return binding


def reader(
    access: ArchiveAccessService,
    bindings: BindingRepository,
    caller: Caller,
    ledger_id: str,
) -> ArchiveBinding:
    """The binding of a ledger ``caller`` may read."""
    return admitted(access.may_read(caller, ledger_id), bindings, ledger_id)
