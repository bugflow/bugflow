"""An explicit association for one retained record, without access grants."""

from dataclasses import dataclass
from typing import Literal

from bugflow.shared.domain.values.repository_origin import RepositoryOrigin

RecordKind = Literal["journal", "snapshot", "ledger"]


@dataclass(frozen=True)
class RepositoryAssociation:
    kind: RecordKind
    record_id: str
    origin: RepositoryOrigin

    def __post_init__(self) -> None:
        if self.kind not in ("journal", "snapshot", "ledger"):
            raise ValueError("unknown repository record kind")
        if not self.record_id:
            raise ValueError("repository record id is empty")


class AssociationConflictError(ValueError):
    """The record already has another origin; it cannot be reassigned."""


class AssociationRecordMissingError(ValueError):
    """No retained record has this kind and identifier."""
