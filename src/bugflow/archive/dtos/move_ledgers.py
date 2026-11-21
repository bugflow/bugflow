"""The request and response of ``MoveLedgersUseCase``."""

from pydantic import BaseModel, ConfigDict


class MoveLedgersRequest(BaseModel):
    """A repository on one forge, renamed from ``repo`` to ``to``."""

    model_config = ConfigDict(frozen=True)

    forge: str
    #: The old name, as ``owner/name``.
    repo: str
    #: The new name, as ``owner/name``.
    to: str


class MoveLedgersResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: The ledgers now bound to the new name, each at its old scope.
    moved: tuple[str, ...]
    #: The ledgers left on the old name, because each has an origin,
    #: which names the old name.
    stayed: tuple[str, ...]
