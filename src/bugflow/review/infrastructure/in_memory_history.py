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
from bugflow.shared.domain.repositories.repository_associations import (
    RepositoryAssociations,
)
from bugflow.shared.domain.values.repository_association import (
    RepositoryAssociationUnresolvedError,
)


class InMemoryHistory:
    def __init__(
        self,
        events: Sequence[StoredReviewEvent] = (),
        associations: RepositoryAssociations | None = None,
    ) -> None:
        self._associations = associations
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
                or entry.pr_number not in scope.pr_numbers
            ):
                continue
            if scope.correlation is not None and (
                entry.workflow_id != scope.correlation.workflow_id
                or entry.run_id != scope.correlation.run_id
            ):
                continue
            if scope.origin is None:
                if entry.repo != scope.repo:
                    continue
            else:
                associated = (
                    self._associations.origin_for(
                        "journal", str(entry.event_id)
                    )
                    if self._associations is not None
                    else None
                )
                if associated is None and entry.repo == scope.repo:
                    raise RepositoryAssociationUnresolvedError(
                        "history contains unresolved repository associations"
                    )
                if associated is None or str(associated) != scope.origin:
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
