"""The rule for letting a caller reach a ledger.

Two things are checked, in this order: whether the caller has the right
role, and then whether the ledger is registered here.

The order matters. A caller without the role gets the same refusal for
every ledger id, registered or not, so they cannot use the answers to find
out which ledgers exist.
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
    """Return the ledger's binding if the caller may proceed.

    ``allowed`` is whether the caller has the role needed. If not, the
    refusal is "access". If the ledger is not registered here, the refusal
    is "absent".
    """
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
    """Return the ledger's binding if ``caller`` may read the ledger. Refuses
    as ``admitted`` does.
    """
    return admitted(access.may_read(caller, ledger_id), bindings, ledger_id)
