"""The request and response of ``DescribeArchiveUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.shared.domain.values.caller import Caller


class DescribeArchiveRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ledger_id: str
    caller: Caller


class DescribeArchiveResponse(BaseModel):
    """What is stored of the ledger. This is the answer to the protocol's
    "describe" operation.
    """

    model_config = ConfigDict(frozen=True)

    ledger_id: str
    head: str | None
    events: int
    root: str | None
    erased: tuple[str, ...]
    #: ``protocols`` is the protocol versions served. ``retiring`` gives, for a
    #: version about to be dropped, the date after which it may be.
    protocols: tuple[int, ...] = (1, 2)
    retiring: tuple[tuple[int, str], ...] = ()
