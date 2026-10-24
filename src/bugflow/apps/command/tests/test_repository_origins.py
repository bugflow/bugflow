import json
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa

from bugflow.apps.command.command import run
from bugflow.apps.command.repository_origins import apply_mapping, inventory
from bugflow.shared.domain.values.repository_association import (
    AssociationRecordMissingError,
)
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.migrations import upgrade


def seed(database_url: str) -> tuple[str, str, str]:
    upgrade(database_url)
    event, snapshot, ledger = str(uuid4()), str(uuid4()), str(uuid4())
    engine = sa.create_engine(engine_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text("""
                INSERT INTO forge_journal
                    (event_id, occurred_at, event_type, forge, repo,
                     workflow_id, run_id, payload)
                VALUES (:id, now(), 'pr.observed', 'forgejo', 'a/b', '', '',
                        '{}')
            """),
                {"id": event},
            )
            connection.execute(
                sa.text("""
                INSERT INTO pull_request_snapshot (snapshot_id, body)
                VALUES (:id, '{"ref": {"forge": "forgejo", "owner": "a",
                                     "repo": "b", "number": 1}}')
            """),
                {"id": snapshot},
            )
            connection.execute(
                sa.text("""
                INSERT INTO archive_binding (ledger_id, forge, repo, scope)
                VALUES (:id, 'forgejo', 'a/b', '')
            """),
                {"id": ledger},
            )
    finally:
        engine.dispose()
    return event, snapshot, ledger


def test_inventory_and_mapping_preserve_identifiers_and_bytes(
    database_url: str,
    tmp_path: Path,
) -> None:
    event, snapshot, ledger = seed(database_url)
    ids = {event, snapshot, ledger}
    before = [r for r in inventory(database_url) if r["record_id"] in ids]
    assert len(before) == 3
    assert all(
        r["status"] == "unresolved" and r["origin"] is None for r in before
    )
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "kind": "journal",
                    "record_id": event,
                    "origin": "one.example/a/b",
                },
                {
                    "kind": "snapshot",
                    "record_id": snapshot,
                    "origin": "two.example/a/b",
                },
            ]
        )
    )
    assert apply_mapping(database_url, mapping) == 2
    assert apply_mapping(database_url, mapping) == 2
    after = [r for r in inventory(database_url) if r["record_id"] in ids]
    for old, new in zip(before, after, strict=True):
        assert {
            k: v for k, v in old.items() if k not in ("origin", "status")
        } == {k: v for k, v in new.items() if k not in ("origin", "status")}
    assert (
        next(r for r in after if r["kind"] == "ledger")["status"]
        == "unresolved"
    )
    engine = sa.create_engine(engine_url(database_url))
    try:
        with engine.connect() as connection:
            assert connection.execute(
                sa.text(
                    "SELECT body FROM pull_request_snapshot "
                    "WHERE snapshot_id = :id"
                ),
                {"id": snapshot},
            ).scalar_one() == {
                "ref": {
                    "forge": "forgejo",
                    "owner": "a",
                    "repo": "b",
                    "number": 1,
                }
            }
            assert (
                connection.execute(
                    sa.text(
                        "SELECT payload FROM journal WHERE event_id = :id"
                    ),
                    {"id": event},
                ).scalar_one()
                == {}
            )
    finally:
        engine.dispose()


def test_missing_record_refuses_whole_mapping(
    database_url: str, tmp_path: Path
) -> None:
    _, snapshot, _ = seed(database_url)
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "kind": "snapshot",
                    "record_id": snapshot,
                    "origin": "one.example/a/b",
                },
                {
                    "kind": "snapshot",
                    "record_id": "missing",
                    "origin": "one.example/a/b",
                },
            ]
        )
    )
    with pytest.raises(AssociationRecordMissingError):
        apply_mapping(database_url, mapping)
    assert (
        next(r for r in inventory(database_url) if r["record_id"] == snapshot)[
            "origin"
        ]
        is None
    )


def test_command_reports_unresolved_and_missing_configuration(
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, snapshot, _ = seed(database_url)
    assert run(["repository-origins"], {"DATABASE_URL": database_url}) == 0
    rows = json.loads(capsys.readouterr().out)
    assert (
        next(r for r in rows if r["record_id"] == snapshot)["status"]
        == "unresolved"
    )
    assert run(["repository-origins"], {}) == 2
    assert "DATABASE_URL" in capsys.readouterr().err


def test_mapping_errors_do_not_echo_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        '[{"kind":"snapshot","record_id":"x",'
        '"origin":"https://user:secret@host/a/b"}]'
    )
    assert (
        run(
            ["repository-origins", "--apply", str(mapping)],
            {
                "DATABASE_URL": "postgresql://unused",
            },
        )
        == 2
    )
    output = capsys.readouterr()
    assert "secret" not in output.err + output.out
