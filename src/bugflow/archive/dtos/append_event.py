"""The request and response of ``AppendEventUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.shared.domain.values.caller import Caller


class AppendEventRequest(BaseModel):
    """One event sent by a client, to be checked and stored.

    ``name`` is the event's file name and ``data`` its bytes. ``files`` are
    the files the event adds, by CID. ``claims`` is what the client says
    about where the event came from.

    ``following`` is only for old ledgers whose first events carry no
    ledger id: it is the events that come after this one, sent so the
    server can tell which ledger this event belongs to. They are checked
    and not stored.

    Everything here comes from outside and is untrusted. The event, the
    files and the later events are checked; the claims are only recorded.
    """

    model_config = ConfigDict(frozen=True)

    ledger_id: str
    caller: Caller
    name: str
    data: bytes
    files: dict[str, bytes]
    claims: dict[str, str]
    following: tuple[tuple[str, bytes], ...] = ()


class AppendEventResponse(BaseModel):
    """What is stored of the ledger after the append."""

    model_config = ConfigDict(frozen=True)

    ledger_id: str
    head: str | None
    events: int
    root: str | None
    erased: tuple[str, ...]
    protocols: tuple[int, ...] = (1, 2)
    retiring: tuple[tuple[int, str], ...] = ()
    # False if this exact event was already stored at that number, so
    # sending it again changed nothing.
    appended: bool
