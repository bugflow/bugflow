"""Inventory retained references and apply explicit operator mappings."""

import json
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from bugflow.shared.domain.values.repository_association import (
    AssociationRecordMissingError,
    RepositoryAssociation,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.serde import from_json
from bugflow.shared.infrastructure.sqlalchemy_repository_associations import (
    SqlAlchemyRepositoryAssociations,
)

# Query only identifiers and provenance. Bodies and personal data stay in SQL.
_INVENTORY = sa.text("""SELECT r.kind, r.record_id, r.forge, r.repo, a.origin,
       CASE WHEN a.origin IS NULL THEN 'unresolved' ELSE 'associated' END
           AS status
FROM (
    SELECT 'journal' AS kind, event_id::text AS record_id, forge, repo
    FROM journal WHERE repo <> ''
    UNION ALL
    SELECT 'snapshot', snapshot_id, body->'ref'->>'forge',
           (body->'ref'->>'owner') || '/' || (body->'ref'->>'repo')
    FROM pull_request_snapshots
    UNION ALL
    SELECT 'ledger', ledger_id, forge, repo FROM archive_bindings
) r LEFT JOIN repository_associations a
  ON a.kind = r.kind AND a.record_id = r.record_id
ORDER BY r.kind, r.record_id
""")


def inventory(database_url: str) -> list[dict[str, Any]]:
    engine = sa.create_engine(engine_url(database_url))
    try:
        with engine.connect() as connection:
            return [
                dict(row) for row in connection.execute(_INVENTORY).mappings()
            ]
    finally:
        engine.dispose()


def apply_mapping(database_url: str, path: Path) -> int:
    """Require exact record identifiers; never infer a host from forge kind."""
    entries = json.loads(path.read_text())
    if not isinstance(entries, list):
        raise ValueError("repository mapping must be a JSON array")
    associations: list[RepositoryAssociation] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "kind",
            "record_id",
            "origin",
        }:
            raise ValueError("each mapping needs kind, record_id and origin")
        if not all(isinstance(value, str) for value in entry.values()):
            raise ValueError("mapping fields must be strings")
        associations.append(
            from_json(
                RepositoryAssociation,
                {
                    "kind": entry["kind"],
                    "record_id": entry["record_id"],
                    "origin": {
                        "value": str(RepositoryOrigin.parse(entry["origin"]))
                    },
                },
            )
        )
    known = {
        (row["kind"], row["record_id"]) for row in inventory(database_url)
    }
    if any((one.kind, one.record_id) not in known for one in associations):
        raise AssociationRecordMissingError("mapping names an absent record")
    store = SqlAlchemyRepositoryAssociations(database_url)
    try:
        store.associate(tuple(associations))
    finally:
        store.close()
    return len(associations)
