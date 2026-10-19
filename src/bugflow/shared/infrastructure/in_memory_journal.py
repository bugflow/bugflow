"""A journal that keeps its entries in a list, for tests.

It follows the same rules as the Postgres journal: an entry whose id is
already present is skipped, a payload that cannot be written as JSON is
refused, and every entry is marked with the build.
"""

import json
from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.models.journal_provenance import (
    check_retry,
    resolve_origin,
    scope_of,
    validate_assertion,
)
from bugflow.shared.domain.repositories.repository_associations import (
    RepositoryAssociations,
)
from bugflow.shared.domain.values.repository_association import (
    RepositoryAssociation,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin
from bugflow.shared.infrastructure.in_memory_repository_associations import (
    InMemoryRepositoryAssociations,
)


class InMemoryJournal:
    def __init__(
        self,
        build: str | None = None,
        *,
        associations: RepositoryAssociations | None = None,
    ) -> None:
        self.entries: list[JournalEntry] = []
        self._build = build
        self._associations = (
            associations
            if associations is not None
            else InMemoryRepositoryAssociations()
        )

    def append(self, entries: Sequence[JournalEntry]) -> None:
        for entry in entries:
            validate_assertion(entry)
        for entry in entries:
            json.dumps(entry.payload)
        scopes = {scope_of(entry) for entry in entries}
        origins = {
            scope: resolve_origin(
                scope,
                (
                    entry.origin
                    for entry in entries
                    if scope_of(entry) == scope
                    and (entry.origin is not None or entry.origin_asserted)
                ),
                (
                    self._origin(entry.event_id)
                    for entry in self.entries
                    if scope_of(entry) == scope
                ),
            )
            for scope in scopes
        }
        known = {entry.event_id: entry for entry in self.entries}
        pending: list[JournalEntry] = []
        associations: dict[UUID, RepositoryAssociation] = {}
        for entry in entries:
            if entry.event_id in known:
                association = associations.get(entry.event_id)
                origin = (
                    str(association.origin)
                    if association
                    else self._origin(entry.event_id)
                )
                check_retry(entry, scope_of(known[entry.event_id]), origin)
                continue
            origin = origins[scope_of(entry)]
            if origin is not None:
                associations[entry.event_id] = RepositoryAssociation(
                    kind="journal",
                    record_id=str(entry.event_id),
                    origin=RepositoryOrigin(origin),
                )
            stored = replace(
                entry, build=self._build, origin=None, origin_asserted=False
            )
            pending.append(stored)
            known[entry.event_id] = stored
        self._associations.associate(tuple(associations.values()))
        self.entries.extend(pending)

    def _origin(self, event_id: UUID) -> str | None:
        origin = self._associations.origin_for("journal", str(event_id))
        return str(origin) if origin is not None else None

    def has_event(self, event_id: UUID) -> bool:
        return any(e.event_id == event_id for e in self.entries)
