"""DTOs for AppendEventUseCase: what asks and what comes back."""

from pydantic import BaseModel, ConfigDict

from bugflow.shared.domain.values.caller import Caller


class AppendEventRequest(BaseModel):
    """One event of a ledger, as a client that sealed it sends it: the
    ledger file's name and bytes, the files it or earlier events enrol by
    their CIDs, and what the client says of where the event came from.
    ``following`` is the ledger's later events, each a file's name and
    bytes in order, that a client sends with an event that names no
    ledger: by them the keeper knows whose the event is, and it keeps
    none of them. All of it is content from a repository under study and
    none of it is trusted: the event, the files and the later events are
    verified, the claims recorded."""

    model_config = ConfigDict(frozen=True)

    ledger_id: str
    caller: Caller
    name: str
    data: bytes
    files: dict[str, bytes]
    claims: dict[str, str]
    following: tuple[tuple[str, bytes], ...] = ()


class AppendEventResponse(BaseModel):
    """What is kept of the ledger after the event."""

    model_config = ConfigDict(frozen=True)

    ledger_id: str
    head: str | None
    events: int
    root: str | None
    erased: tuple[str, ...]
    protocols: tuple[int, ...] = (1, 2)
    retiring: tuple[tuple[int, str], ...] = ()
    # False when the event was already the ledger's event of that number,
    # and sending it again changed nothing.
    appended: bool
