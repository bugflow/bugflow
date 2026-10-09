"""The request and response of ``BindLedgerUseCase``."""

from pydantic import BaseModel, ConfigDict


class BindLedgerRequest(BaseModel):
    """An operator's instruction to register a ledger: this server is to store
    its archive, for the named repository and scope.
    """

    model_config = ConfigDict(frozen=True)

    ledger_id: str
    forge: str
    repo: str
    scope: str = ""


class BoundTo(BaseModel):
    """The repository and scope a ledger was registered for."""

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
    # False if the ledger was already registered for exactly this
    # repository and scope, so nothing was changed or recorded.
    bound: bool
    # What the ledger was registered for before, if this changed it.
    replaces: BoundTo | None
    # Other ledgers registered for the same scope. A scope normally has
    # one ledger. More than one can mean an archive was replaced or a
    # ledger was started afresh, so the operator is shown them.
    beside: tuple[str, ...]
