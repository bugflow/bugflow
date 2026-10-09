"""The events of kept ledgers, held in memory, for tests."""

from bugflow.archive.domain.models.kept_event import KeptEvent
from bugflow.archive.domain.repositories.kept_events import EventTakenError


class InMemoryKeptEvents:
    def __init__(self) -> None:
        self._kept: dict[tuple[str, int], KeptEvent] = {}

    def of_ledger(self, ledger_id: str) -> list[KeptEvent]:
        return [
            self._kept[key]
            for key in sorted(self._kept)
            if key[0] == ledger_id
        ]

    def add(self, event: KeptEvent) -> None:
        key = (event.ledger_id, event.number)
        if key in self._kept:
            raise EventTakenError(
                f"ledger {event.ledger_id} has an event {event.number}"
            )
        self._kept[key] = event
