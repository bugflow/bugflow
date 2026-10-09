"""A journal in a list, for tests.

It applies the rules a stored journal does: a repeated event id is
ignored, a payload that JSON cannot say is refused, and every entry is
stamped with the build.
"""

import json
from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from bugflow.shared.domain.models.journal_entry import JournalEntry


class InMemoryJournal:
    def __init__(self, build: str | None = None) -> None:
        self.entries: list[JournalEntry] = []
        self._build = build

    def append(self, entries: Sequence[JournalEntry]) -> None:
        for entry in entries:
            json.dumps(entry.payload)
        known = {e.event_id for e in self.entries}
        for entry in entries:
            if entry.event_id not in known:
                self.entries.append(replace(entry, build=self._build))
                known.add(entry.event_id)

    def has_event(self, event_id: UUID) -> bool:
        return any(e.event_id == event_id for e in self.entries)
