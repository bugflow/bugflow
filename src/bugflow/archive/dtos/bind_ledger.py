"""DTOs for BindLedgerUseCase: what asks and what comes back."""

from pydantic import BaseModel, ConfigDict


class BindLedgerRequest(BaseModel):
    """An operator's declaration that this server keeps the archive of
    one ledger, for a scope of a repository."""

    model_config = ConfigDict(frozen=True)

    ledger_id: str
    forge: str
    repo: str
    scope: str = ""


class BoundTo(BaseModel):
    """Where a ledger was bound before."""

    model_config = ConfigDict(frozen=True)

    forge: str
    repo: str
    scope: str


class BindLedgerResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ledger_id: str
    forge: str
    repo: str
    scope: str
    # False when the ledger was already bound exactly so, and nothing was
    # written or recorded.
    bound: bool
    # Where the ledger was bound until now, when this moved it.
    replaces: BoundTo | None
    # The other ledgers bound to the same scope. More than one is what an
    # archive replaced looks like, and what a scope whose ledger was
    # started again looks like; the operator is told, and decides.
    beside: tuple[str, ...]
