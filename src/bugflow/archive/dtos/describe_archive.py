"""DTOs for DescribeArchiveUseCase: what asks and what comes back."""

from pydantic import BaseModel, ConfigDict

from bugflow.shared.domain.values.caller import Caller


class DescribeArchiveRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ledger_id: str
    caller: Caller


class DescribeArchiveResponse(BaseModel):
    """What is kept of the ledger, as the remote archive protocol's
    describe answers."""

    model_config = ConfigDict(frozen=True)

    ledger_id: str
    head: str | None
    events: int
    root: str | None
    erased: tuple[str, ...]
    #: The versions of the protocol served, and by version the date
    #: after which one may stop being served.
    protocols: tuple[int, ...] = (1, 2)
    retiring: tuple[tuple[int, str], ...] = ()
