"""Persistent provenance associations, separate from repository authority."""

from typing import Protocol

from bugflow.shared.domain.values.repository_association import (
    RecordKind,
    RepositoryAssociation,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin


class RepositoryAssociations(Protocol):
    def associate(
        self, associations: tuple[RepositoryAssociation, ...]
    ) -> None:
        """Store the entire batch or refuse it on any conflicting origin."""
        ...

    def origin_for(
        self, kind: RecordKind, record_id: str
    ) -> RepositoryOrigin | None:
        """Return the explicit association, or None when unresolved."""
        ...
