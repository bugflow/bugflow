"""Interface: the events of the ledgers whose archives are kept."""

from typing import Protocol

from bugflow.archive.domain.models.kept_event import KeptEvent
from bugflow.shared.domain.repositories.base import BaseRepository


class EventTakenError(Exception):
    """The ledger already has an event of that number.

    Two clients appended at once, or one appended twice: the first to
    arrive is the ledger's event and the other is refused, never
    merged."""


class KeptEventRepository(BaseRepository[KeptEvent], Protocol):
    def of_ledger(self, ledger_id: str) -> list[KeptEvent]:
        """The ledger's events in order, none for a ledger with none."""
        ...

    def add(self, event: KeptEvent) -> None:
        """Keep the event. Raises EventTakenError when the ledger has one
        of that number already: an event is kept once and never
        replaced."""
        ...
