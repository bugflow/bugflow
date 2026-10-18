"""A bounded history reader over stored events supplied in memory."""

import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

from bugflow.review.domain.errors import HistoryTooLargeError
from bugflow.review.domain.models.history import (
    HistoryLimits,
    HistoryScope,
    StoredReviewEvent,
)


class InMemoryHistory:
    def __init__(self, events: Sequence[StoredReviewEvent] = ()) -> None:
        # The first stored fact wins, as it does in the journal.
        self.events: dict[UUID, StoredReviewEvent] = {}
        for event in events:
            self.events.setdefault(event.entry.event_id, event)

    def entries_for_history(
        self, scope: HistoryScope, limits: HistoryLimits
    ) -> tuple[StoredReviewEvent, ...]:
        found = []
        byte_count = 0
        for event in tuple(self.events.values()):
            entry = event.entry
            if (
                entry.forge != scope.forge
                or entry.repo != scope.repo
                or entry.pr_number not in scope.pr_numbers
            ):
                continue
            if scope.correlation is not None and (
                entry.workflow_id != scope.correlation.workflow_id
                or entry.run_id != scope.correlation.run_id
            ):
                continue
            found.append(event)
            if len(found) > limits.max_events:
                raise HistoryTooLargeError("history exceeds the event limit")
            columns = asdict(entry) | {
                "recorded_at": event.recorded_at,
                "policy_repository": event.policy_repository,
                "policy_commit": event.policy_commit,
                "policy_content": event.policy_content,
            }
            byte_count += 1024
            for name, value in columns.items():
                if value is None:
                    continue
                text = (
                    json.dumps(value, ensure_ascii=False)
                    if name == "payload"
                    else str(value)
                )
                byte_count += len(text.encode("utf-8"))
            if byte_count > limits.max_bytes:
                raise HistoryTooLargeError("history exceeds the byte limit")
        return tuple(
            sorted(
                found,
                key=lambda e: (
                    e.entry.occurred_at,
                    e.recorded_at or datetime.max.replace(tzinfo=UTC),
                    e.entry.event_id,
                ),
            )
        )
