"""Use case: move the ledgers bound to a renamed repository to its new
name.

Each ledger bound to the old name whose origin is unresolved is bound
again to the new name, at the scope it had, through
``BindLedgerUseCase``, so each move is recorded as ``archive.bound``
with what it replaced, as an operator's ``bugflow declare --archive``
is. A ledger with an origin stays: its origin names the old name, and
an established origin is never changed (see repository-origins.md).

Who may append to a ledger is decided by role, not by the repository
it is bound to, so a client appending to a moved ledger is not refused.
"""

from bugflow.archive.domain.repositories.bindings import BindingRepository
from bugflow.archive.dtos.bind_ledger import BindLedgerRequest
from bugflow.archive.dtos.move_ledgers import (
    MoveLedgersRequest,
    MoveLedgersResponse,
)
from bugflow.archive.usecases.bind_ledger import BindLedgerUseCase


class MoveLedgersUseCase:
    """Takes a repository's old and new names. Returns which ledgers
    moved and which stayed."""

    def __init__(
        self, bindings: BindingRepository, binder: BindLedgerUseCase
    ) -> None:
        self._bindings = bindings
        self._binder = binder

    def execute(self, request: MoveLedgersRequest) -> MoveLedgersResponse:
        moved: list[str] = []
        stayed: list[str] = []
        for one in self._bindings.bindings():
            if (one.forge, one.repo) != (request.forge, request.repo):
                continue
            if one.origin is not None:
                stayed.append(one.ledger_id)
                continue
            self._binder.execute(
                BindLedgerRequest(
                    ledger_id=one.ledger_id,
                    forge=one.forge,
                    repo=request.to,
                    scope=one.scope,
                )
            )
            moved.append(one.ledger_id)
        return MoveLedgersResponse(moved=tuple(moved), stayed=tuple(stayed))
