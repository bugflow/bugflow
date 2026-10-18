"""Repository associations for tests without a database."""

from bugflow.shared.domain.values.repository_association import (
    AssociationConflictError,
    RecordKind,
    RepositoryAssociation,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin


class InMemoryRepositoryAssociations:
    def __init__(self) -> None:
        self._origins: dict[tuple[RecordKind, str], RepositoryOrigin] = {}

    def associate(
        self, associations: tuple[RepositoryAssociation, ...]
    ) -> None:
        pending = self._origins.copy()
        for one in associations:
            key = (one.kind, one.record_id)
            if key in pending and pending[key] != one.origin:
                raise AssociationConflictError(
                    "retained record already has another repository origin"
                )
            pending[key] = one.origin
        self._origins = pending

    def origin_for(
        self, kind: RecordKind, record_id: str
    ) -> RepositoryOrigin | None:
        return self._origins.get((kind, record_id))
