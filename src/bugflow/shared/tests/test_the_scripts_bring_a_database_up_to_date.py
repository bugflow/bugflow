"""Tests of the scripts that create and change a database's tables: that a
database records what it has run, that programs starting together do not
collide, and that tables already there are kept.

Skipped unless DATABASE_URL names a Postgres server.
"""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.script.revision import ResolutionError
from sqlalchemy.dialects.postgresql import JSONB

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.migrations import (
    VERSION_TABLE,
    downgrade,
    pending,
    upgrade,
)
from bugflow.shared.tests.postgres import scratch_database
from bugflow.shared.tests.test_the_journal_in_postgres import entry, rows

LAST = "0020"
#: The last script before the journal gained its keys, at which a
#: database built by an earlier program's scripts is seeded below.
BEFORE_KEYS = "0009"


@pytest.fixture
def empty() -> Iterator[str]:
    yield from scratch_database()


def last_run(database_url: str) -> list[str]:
    engine = sa.create_engine(engine_url(database_url))
    try:
        with engine.connect() as connection:
            return [
                row[0]
                for row in connection.execute(
                    sa.text(f"select version_num from {VERSION_TABLE}")
                )
            ]
    finally:
        engine.dispose()


def test_a_database_records_the_last_script_it_ran(empty: str) -> None:
    upgrade(empty)
    assert last_run(empty) == [LAST]

    upgrade(empty)
    assert last_run(empty) == [LAST]


def test_programs_that_start_together_do_not_collide(empty: str) -> None:
    with ThreadPoolExecutor(max_workers=4) as together:
        for done in [together.submit(upgrade, empty) for _ in range(4)]:
            done.result()
    assert last_run(empty) == [LAST]


def test_a_table_that_is_already_there_keeps_its_rows(empty: str) -> None:
    """A journal row written before the journal had its keys is kept,
    and the script that adds the keys fills them for it."""
    engine = sa.create_engine(engine_url(empty))
    try:
        made = replace(entry("already-here"), pr_number=7)
        seed_before_keys(empty, engine, made)

        upgrade(empty)

        (row,) = rows(engine, made.event_id)
        assert row["pull_request_id"] is not None
        assert row["workflow_run_id"] is not None
        assert last_run(empty) == [LAST]
    finally:
        engine.dispose()


def test_columns_that_are_already_there_are_left_alone(empty: str) -> None:
    """A row's columns survive the script that adds others beside them."""
    engine = sa.create_engine(engine_url(empty))
    try:
        made = entry("named")
        seed_before_keys(empty, engine, made, "example-org/policies")

        upgrade(empty)

        (row,) = rows(engine, made.event_id)
        assert row["policy_repository"] == "example-org/policies"
        assert last_run(empty) == [LAST]
    finally:
        engine.dispose()


def test_the_keys_name_the_entities_the_text_does(empty: str) -> None:
    """The script makes one row per distinct forge, repository, pull
    request, workflow and run the journal names, and the journal's keys
    point at them."""
    engine = sa.create_engine(engine_url(empty))
    try:
        first = replace(entry("first"), pr_number=7)
        second = replace(entry("second"), pr_number=7)
        seed_before_keys(empty, engine, first)
        seed_before_keys(empty, engine, second, run=False)

        upgrade(empty)

        with engine.connect() as connection:
            named = connection.execute(
                sa.text(
                    "select f.name, r.name, p.number, w.name, wr.name "
                    "from journal j "
                    "join pull_request p on p.id = j.pull_request_id "
                    "join repository r on r.id = p.repository_id "
                    "join forge f on f.id = r.forge_id "
                    "join workflow_run wr on wr.id = j.workflow_run_id "
                    "join workflow w on w.id = wr.workflow_id "
                    "where j.event_id = :event_id"
                ),
                {"event_id": first.event_id},
            ).one()
            counts = connection.execute(
                sa.text(
                    "select (select count(*) from forge), "
                    "(select count(*) from repository), "
                    "(select count(*) from pull_request), "
                    "(select count(*) from workflow), "
                    "(select count(*) from workflow_run)"
                )
            ).one()
        assert tuple(named) == (
            first.forge,
            first.repo,
            first.pr_number,
            first.workflow_id,
            first.run_id,
        )
        assert tuple(counts) == (1, 1, 1, 1, 1)
    finally:
        engine.dispose()


def seed_before_keys(
    database_url: str,
    engine: sa.Engine,
    made: JournalEntry,
    policy_repository: str | None = None,
    run: bool = True,
    table: str = "journal",
) -> None:
    """Write a row as a program before the journal had its keys did:
    into a database at the script before them, by the text columns.
    ``table`` is the journal to write to where the database is past the
    division."""
    if run:
        upgrade(database_url)
        downgrade(database_url, BEFORE_KEYS)
    values = asdict(made)
    values.pop("origin")
    values.pop("origin_asserted")
    values["policy_repository"] = policy_repository
    columns = ", ".join(values)
    placeholders = ", ".join(f":{name}" for name in values)
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                f"insert into {table} ({columns}) values ({placeholders})"
            ).bindparams(sa.bindparam("payload", type_=JSONB)),
            values,
        )


#: A deployment's own script: a branch of the package's that depends on
#: the script that made the journal, since its table refers to an event.
DEPLOYMENT_SCRIPT = """
import sqlalchemy as sa
from alembic import op

revision = "d0001"
down_revision = None
branch_labels = ("deployment",)
depends_on = "0002"


def upgrade() -> None:
    op.create_table(
        "deployment_notes",
        sa.Column("event_id", sa.Text, primary_key=True),
        sa.Column("note", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("deployment_notes")
"""


def test_a_deployments_own_scripts_run_as_a_branch_of_the_packages(
    empty: str, tmp_path: Path
) -> None:
    """The deployment's script runs after the package script it depends
    on, and the one version table records both heads."""
    (tmp_path / "d0001_deployment_notes.py").write_text(DEPLOYMENT_SCRIPT)
    scripts = [str(tmp_path)]

    not_run = pending(empty, scripts)
    assert not_run.index("d0001_deployment_notes") > not_run.index(
        "s0002_the_journal"
    )

    upgrade(empty, scripts)

    assert pending(empty, scripts) == []
    assert set(last_run(empty)) == {LAST, "d0001"}
    engine = sa.create_engine(engine_url(empty))
    try:
        assert sa.inspect(engine).has_table("deployment_notes")
    finally:
        engine.dispose()


def test_a_branch_not_yet_recorded_is_pending_on_an_up_to_date_database(
    empty: str, tmp_path: Path
) -> None:
    """A deployment adds its branch to a database that has run every
    package script, and the branch alone is what remains to run."""
    (tmp_path / "d0001_deployment_notes.py").write_text(DEPLOYMENT_SCRIPT)
    upgrade(empty)

    assert pending(empty, [str(tmp_path)]) == ["d0001_deployment_notes"]


def test_a_database_with_a_branch_is_read_with_the_branchs_scripts(
    empty: str, tmp_path: Path
) -> None:
    """The package's scripts alone do not know the branch's head, and
    say so rather than run anything."""
    (tmp_path / "d0001_deployment_notes.py").write_text(DEPLOYMENT_SCRIPT)
    upgrade(empty, [str(tmp_path)])

    with pytest.raises(ResolutionError, match="d0001"):
        pending(empty)


def tables(database_url: str) -> set[str]:
    engine = sa.create_engine(engine_url(database_url))
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_the_renames_can_be_backed_out_and_run_again(empty: str) -> None:
    """A deployment returns to the previous tag by reversing the script
    that renamed the tables, and moves forward again by running it."""
    upgrade(empty)
    assert {"spend_binding", "repository_association"} <= tables(empty)

    downgrade(empty, "0008")

    assert last_run(empty) == ["0008"]
    assert {"spend_bindings", "repository_associations"} <= tables(empty)
    assert "spend_binding" not in tables(empty)

    upgrade(empty)

    assert last_run(empty) == [LAST]
    assert "spend_bindings" not in tables(empty)


def test_the_archives_facts_already_there_are_unpacked(
    empty: str, tmp_path: Path
) -> None:
    """A sealed fact written before the typed tables existed is unpacked
    by the script that makes them, claims and all."""
    upgrade(empty)
    downgrade(empty, "0011")
    sealed = replace(
        entry("sealed-before"),
        event_type="archive.sealed",
        payload={
            "ledger_id": "ledger-9",
            "scope": "notes",
            "name": "0001-first",
            "head": "h",
            "root": "r",
            "events": 1,
            "files": 1,
            "bytes": 10,
            "caller": "s",
            "client": "c",
            "claims": {"branch": "master"},
        },
    )
    seed_before_keys(
        empty, _engine(empty), sealed, run=False, table="archive_journal"
    )

    upgrade(empty)

    engine = sa.create_engine(engine_url(empty))
    try:
        with engine.connect() as connection:
            claim = connection.execute(
                sa.text(
                    "select c.value from archive_seal s "
                    "join archive_seal_claim c on c.event_id = s.event_id "
                    "where s.event_id = :id"
                ),
                {"id": sealed.event_id},
            ).scalar_one()
    finally:
        engine.dispose()
    assert claim == "master"


def test_an_archive_fact_with_an_unknown_key_stops_the_script(
    empty: str,
) -> None:
    upgrade(empty)
    downgrade(empty, "0011")
    odd = replace(
        entry("odd"),
        event_type="archive.refused",
        payload={
            "ledger_id": "l",
            "scope": "s",
            "name": "n",
            "kind": "k",
            "caller": "c",
            "client": "x",
            "reason": "a key the inventory never saw",
        },
    )
    seed_before_keys(
        empty, _engine(empty), odd, run=False, table="archive_journal"
    )

    with pytest.raises(Exception, match="keys the inventory did not find"):
        upgrade(empty)


def test_the_forges_facts_already_there_are_unpacked(empty: str) -> None:
    """An observation written before the typed tables existed is unpacked
    by the script that makes them, commits and policies and all, and an
    older observation with no scope has no policy rows."""
    upgrade(empty)
    downgrade(empty, "0012")
    observed = replace(
        entry("observed-before"),
        event_type="pr.observed",
        payload={
            "delivery_id": "d-2",
            "delivery_ids": ["d-1", "d-2"],
            "snapshot_id": "snap-1",
            "corpus": {"doctrine": "v3", "judge": "v9"},
            "installed": {"narrative": "1.2"},
            "reviewed_for": ["narrative"],
            "held": ["narrative", "security"],
            "title": "Add a thing",
            "head_branch": "thing",
            "base_branch": "main",
            "author_login": "someone",
            "commits": [
                {
                    "sha": "abc",
                    "author_name": "A",
                    "author_email": "a@x",
                    "author_login": "someone",
                    "committer_name": "GitHub",
                    "committer_email": "noreply@github.com",
                    "committer_login": "web-flow",
                    "verified": True,
                    "verification_reason": "valid",
                }
            ],
            "file_count": 3,
            "changed_lines": 40,
        },
    )
    older = replace(
        entry("observed-earlier"),
        event_type="pr.observed",
        payload={
            "delivery_id": None,
            "delivery_ids": [],
            "snapshot_id": "snap-0",
            "corpus": {"doctrine": "v2", "judge": "v8"},
            "title": "Older",
            "head_branch": "old",
            "base_branch": "main",
            "author_login": "someone",
            "commits": [],
            "file_count": 0,
            "changed_lines": 0,
        },
    )
    engine = _engine(empty)
    seed_before_keys(empty, engine, observed, run=False, table="forge_journal")
    seed_before_keys(empty, engine, older, run=False, table="forge_journal")

    upgrade(empty)

    try:
        with engine.connect() as connection:
            commit = connection.execute(
                sa.text(
                    "select c.author_login, c.verified from "
                    "pull_request_observation_commit c where c.event_id = :id"
                ),
                {"id": observed.event_id},
            ).one()
            policies = connection.execute(
                sa.text(
                    "select standing, policy_id from "
                    "pull_request_observation_policy where event_id = :id "
                    "order by standing, policy_id"
                ),
                {"id": observed.event_id},
            ).all()
            older_policies = connection.execute(
                sa.text(
                    "select count(*) from pull_request_observation_policy "
                    "where event_id = :id"
                ),
                {"id": older.event_id},
            ).scalar_one()
    finally:
        engine.dispose()
    assert tuple(commit) == ("someone", True)
    assert [tuple(p) for p in policies] == [
        ("held", "narrative"),
        ("held", "security"),
        ("reviewed_for", "narrative"),
    ]
    assert older_policies == 0


def test_a_commit_with_an_unknown_key_stops_the_script(empty: str) -> None:
    """The check reaches inside the lists of objects a payload carries."""
    upgrade(empty)
    downgrade(empty, "0012")
    odd = replace(
        entry("odd-commit"),
        event_type="pr.observed",
        payload={
            "delivery_id": None,
            "delivery_ids": [],
            "snapshot_id": "snap-9",
            "corpus": {"doctrine": "v3", "judge": "v9"},
            "title": "Odd",
            "head_branch": "odd",
            "base_branch": "main",
            "author_login": "someone",
            "commits": [{"sha": "abc", "signed_off_by": "someone"}],
            "file_count": 1,
            "changed_lines": 1,
        },
    )
    seed_before_keys(
        empty, _engine(empty), odd, run=False, table="forge_journal"
    )

    with pytest.raises(Exception, match="commits element of a shape"):
        upgrade(empty)


def test_the_reviews_facts_already_there_are_unpacked(empty: str) -> None:
    """A review comment and a label written before the typed tables
    existed are unpacked by the script that makes them, the labels
    removed as rows, and a judged finding carries its judge."""
    upgrade(empty)
    downgrade(empty, "0013")
    commented = replace(
        entry("commented-before"),
        event_type="action.taken",
        payload={
            "action": "review_comment",
            "agent_id": "narrative",
            "performed": True,
            "status": "published",
            "comment_id": 41,
            "verdict": "warn",
            "head_sha": "abc",
            "finding_count": 2,
            "raised_count": 1,
            "fixed_count": 0,
            "dismissed_count": 1,
        },
    )
    labelled = replace(
        entry("labelled-before"),
        event_type="action.taken",
        payload={
            "action": "outcome_label",
            "performed": True,
            "status": "published",
            "label": "review: warn",
            "removed": ["review: fail", "review: pass"],
        },
    )
    raised = replace(
        entry("raised-before"),
        event_type="finding.raised",
        payload={
            "policy_id": "narrative",
            "severity": "warn",
            "clause": "N-3",
            "subject": "x.md",
            "message": "Says too much",
            "judged_by": "judge-1",
            "judge": {
                "model": "m",
                "fingerprint": "f",
                "prompt_hash": "p",
                "input_hash": "i",
                "exchange_id": "e",
            },
            "corpus_version": "v3",
            "agent_id": "narrative",
        },
    )
    engine = _engine(empty)
    for made in (commented, labelled, raised):
        seed_before_keys(
            empty, engine, made, run=False, table="review_journal"
        )

    upgrade(empty)

    try:
        with engine.connect() as connection:
            comment = connection.execute(
                sa.text(
                    "select verdict, dismissed_count, label "
                    "from review_action where event_id = :id"
                ),
                {"id": commented.event_id},
            ).one()
            removed = (
                connection.execute(
                    sa.text(
                        "select label from review_action_removed_label "
                        "where event_id = :id order by label"
                    ),
                    {"id": labelled.event_id},
                )
                .scalars()
                .all()
            )
            judge = connection.execute(
                sa.text(
                    "select judge_model, judge_exchange_id "
                    "from raised_finding where event_id = :id"
                ),
                {"id": raised.event_id},
            ).one()
    finally:
        engine.dispose()
    assert tuple(comment) == ("warn", 1, None)
    assert removed == ["review: fail", "review: pass"]
    assert tuple(judge) == ("m", "e")


def test_an_action_the_inventory_did_not_find_stops_the_script(
    empty: str,
) -> None:
    upgrade(empty)
    downgrade(empty, "0013")
    odd = replace(
        entry("odd-action"),
        event_type="action.taken",
        payload={"action": "assignment", "performed": True, "status": "x"},
    )
    seed_before_keys(
        empty, _engine(empty), odd, run=False, table="review_journal"
    )

    with pytest.raises(Exception, match="action the inventory did not find"):
        upgrade(empty)


def test_the_stocktakes_facts_already_there_are_unpacked(empty: str) -> None:
    """A stocktake and a dispatch written before the typed tables
    existed are unpacked by the script that makes them, the pull
    requests the stocktake covered as rows."""
    upgrade(empty)
    downgrade(empty, "0014")
    taken = replace(
        entry("taken-before"),
        event_type="stocktake.taken",
        payload={
            "layer": "weekly",
            "since": None,
            "until": "2026-10-18T09:00:00+00:00",
            "merged": 2,
            "pull_requests": [7, 9],
            "base_sha": None,
            "head_sha": "abc",
        },
    )
    dispatched = replace(
        entry("dispatched-before"),
        event_type="stocktake.dispatched",
        payload={
            "layer": "weekly",
            "agent_id": "security",
            "base_sha": None,
            "head_sha": "abc",
            "step": "dispatched",
            "remote_id": "r-1",
        },
    )
    engine = _engine(empty)
    for made in (taken, dispatched):
        seed_before_keys(
            empty, engine, made, run=False, table="stocktake_journal"
        )

    upgrade(empty)

    try:
        with engine.connect() as connection:
            stocktake = connection.execute(
                sa.text(
                    "select since, merged, head_sha "
                    "from stocktake where event_id = :id"
                ),
                {"id": taken.event_id},
            ).one()
            covered = (
                connection.execute(
                    sa.text(
                        "select pull_request from stocktake_pull_request "
                        "where event_id = :id order by position"
                    ),
                    {"id": taken.event_id},
                )
                .scalars()
                .all()
            )
            dispatch = connection.execute(
                sa.text(
                    "select step, runner, remote_id "
                    "from stocktake_dispatch where event_id = :id"
                ),
                {"id": dispatched.event_id},
            ).one()
    finally:
        engine.dispose()
    assert tuple(stocktake) == (None, 2, "abc")
    assert covered == [7, 9]
    assert tuple(dispatch) == ("dispatched", None, "r-1")


def test_a_stocktake_with_an_unknown_key_stops_the_script(
    empty: str,
) -> None:
    upgrade(empty)
    downgrade(empty, "0014")
    odd = replace(
        entry("odd-stocktake"),
        event_type="stocktake.taken",
        payload={
            "layer": "weekly",
            "since": None,
            "until": "2026-10-18T09:00:00+00:00",
            "merged": 0,
            "pull_requests": [],
            "base_sha": None,
            "head_sha": None,
            "repositories": 3,
        },
    )
    seed_before_keys(
        empty, _engine(empty), odd, run=False, table="stocktake_journal"
    )

    with pytest.raises(Exception, match="keys the inventory did not find"):
        upgrade(empty)


def test_the_policy_deploys_already_there_are_unpacked(empty: str) -> None:
    """A deploy written before the typed table existed is unpacked by
    the script that makes it, the replaced deployment flattened, and a
    calibration, which a deployment writes, is left as it is."""
    upgrade(empty)
    downgrade(empty, "0015")
    deployed = replace(
        entry("deployed-before"),
        event_type="policies.deployed",
        payload={
            "repository": "o/policies",
            "commit": "def",
            "content_hash": "h2",
            "files": 13,
            "sent_by": "deployer",
            "replaced": {
                "repository": "o/policies",
                "commit": "abc",
                "content_hash": "h1",
            },
        },
    )
    calibrated = replace(
        entry("calibrated-before"),
        event_type="policy.calibrated",
        payload={"policy_id": "narrative", "fidelity": "whole"},
    )
    engine = _engine(empty)
    for made in (deployed, calibrated):
        seed_before_keys(
            empty, engine, made, run=False, table="policy_journal"
        )

    upgrade(empty)

    try:
        with engine.connect() as connection:
            deploy = connection.execute(
                sa.text(
                    "select commit, files, replaced_commit "
                    "from policy_deploy where event_id = :id"
                ),
                {"id": deployed.event_id},
            ).one()
            deploys = connection.execute(
                sa.text("select count(*) from policy_deploy")
            ).scalar_one()
    finally:
        engine.dispose()
    assert tuple(deploy) == ("def", 13, "abc")
    assert deploys == 1


def test_a_deploy_with_an_unknown_key_stops_the_script(empty: str) -> None:
    upgrade(empty)
    downgrade(empty, "0015")
    odd = replace(
        entry("odd-deploy"),
        event_type="policies.deployed",
        payload={
            "repository": "o/policies",
            "commit": "abc",
            "content_hash": "h1",
            "files": 12,
            "sent_by": "deployer",
            "replaced": None,
            "declared": 3,
        },
    )
    seed_before_keys(
        empty, _engine(empty), odd, run=False, table="policy_journal"
    )

    with pytest.raises(Exception, match="keys the inventory did not find"):
        upgrade(empty)


def _columns(database_url: str, table: str) -> set[str]:
    engine = _engine(database_url)
    try:
        with engine.connect() as connection:
            return {
                row[0]
                for row in connection.execute(
                    sa.text(
                        "select column_name from information_schema.columns "
                        "where table_name = :table"
                    ),
                    {"table": table},
                )
            }
    finally:
        engine.dispose()


def test_the_archive_journals_payload_column_goes_once_its_facts_have_tables(
    empty: str,
) -> None:
    """An archive fact written before the typed tables is unpacked by
    0012 and loses its payload to 0017: the column is gone from the
    table, the view reads null for it, and the typed row holds the fact."""
    upgrade(empty)
    downgrade(empty, "0011")
    refused = replace(
        entry("refused-before"),
        event_type="archive.refused",
        payload={
            "ledger_id": "l",
            "scope": "s",
            "name": "n",
            "kind": "k",
            "caller": "c",
            "client": "x",
        },
    )
    seed_before_keys(
        empty, _engine(empty), refused, run=False, table="archive_journal"
    )

    upgrade(empty)

    assert "payload" not in _columns(empty, "archive_journal")
    assert "payload" in _columns(empty, "policy_journal")
    engine = _engine(empty)
    try:
        (row,) = rows(engine, refused.event_id)
        assert row["payload"] is None
        with engine.connect() as connection:
            kind = connection.execute(
                sa.text(
                    "select kind from archive_refusal where event_id = :id"
                ),
                {"id": refused.event_id},
            ).scalar_one()
    finally:
        engine.dispose()
    assert kind == "k"


def test_an_archive_fact_with_no_typed_row_stops_the_column_going(
    empty: str,
) -> None:
    upgrade(empty)
    downgrade(empty, "0016")
    unpacked_by_nothing = replace(
        entry("never-unpacked"),
        event_type="archive.bound",
        payload={"ledger_id": "l", "scope": "s"},
    )
    seed_before_keys(
        empty,
        _engine(empty),
        unpacked_by_nothing,
        run=False,
        table="archive_journal",
    )

    with pytest.raises(Exception, match="have no row in archive_registration"):
        upgrade(empty)


def test_the_forge_journals_payload_column_goes_once_its_facts_have_tables(
    empty: str,
) -> None:
    """A forge fact written before the typed tables is unpacked by 0013
    and loses its payload to 0018: the column is gone from the table,
    the view reads null for it, and the typed row holds the fact."""
    upgrade(empty)
    downgrade(empty, "0012")
    merged = replace(
        entry("merged-before"),
        event_type="pr.merged",
        payload={"delivery_id": "d"},
    )
    seed_before_keys(
        empty, _engine(empty), merged, run=False, table="forge_journal"
    )

    upgrade(empty)

    assert "payload" not in _columns(empty, "forge_journal")
    assert "payload" in _columns(empty, "policy_journal")
    engine = _engine(empty)
    try:
        (row,) = rows(engine, merged.event_id)
        assert row["payload"] is None
        with engine.connect() as connection:
            delivery_id = connection.execute(
                sa.text(
                    "select delivery_id from pull_request_merge "
                    "where event_id = :id"
                ),
                {"id": merged.event_id},
            ).scalar_one()
    finally:
        engine.dispose()
    assert delivery_id == "d"


def test_a_forge_fact_with_no_typed_row_stops_the_column_going(
    empty: str,
) -> None:
    upgrade(empty)
    downgrade(empty, "0017")
    unpacked_by_nothing = replace(
        entry("never-unpacked"),
        event_type="pr.merged",
        payload={"delivery_id": "d"},
    )
    seed_before_keys(
        empty,
        _engine(empty),
        unpacked_by_nothing,
        run=False,
        table="forge_journal",
    )

    with pytest.raises(Exception, match="have no row in pull_request_merge"):
        upgrade(empty)


def _engine(database_url: str) -> sa.Engine:
    return sa.create_engine(engine_url(database_url))


def test_the_review_journals_payload_column_goes_once_its_facts_have_tables(
    empty: str,
) -> None:
    """A review fact written before the typed tables is unpacked by 0014
    and loses its payload to 0019: the column is gone from the table,
    the view reads null for it, and the typed row holds the fact."""
    upgrade(empty)
    downgrade(empty, "0013")
    checked = replace(
        entry("checked-before"),
        event_type="policy.checked",
        payload={"policy_id": "P-01", "clause": "RULE-1", "finding_count": 0},
    )
    seed_before_keys(
        empty, _engine(empty), checked, run=False, table="review_journal"
    )

    upgrade(empty)

    assert "payload" not in _columns(empty, "review_journal")
    assert "payload" in _columns(empty, "policy_journal")
    engine = _engine(empty)
    try:
        (row,) = rows(engine, checked.event_id)
        assert row["payload"] is None
        with engine.connect() as connection:
            clause = connection.execute(
                sa.text(
                    "select clause from policy_check where event_id = :id"
                ),
                {"id": checked.event_id},
            ).scalar_one()
    finally:
        engine.dispose()
    assert clause == "RULE-1"


def test_a_review_fact_with_no_typed_row_stops_the_column_going(
    empty: str,
) -> None:
    upgrade(empty)
    downgrade(empty, "0018")
    unpacked_by_nothing = replace(
        entry("never-unpacked"),
        event_type="policy.checked",
        payload={"policy_id": "P-01", "clause": "RULE-1", "finding_count": 0},
    )
    seed_before_keys(
        empty,
        _engine(empty),
        unpacked_by_nothing,
        run=False,
        table="review_journal",
    )

    with pytest.raises(Exception, match=r"1 of type policy\.checked"):
        upgrade(empty)


def test_a_deployments_own_table_keyed_to_the_review_journal_holds_its_fact(
    empty: str,
) -> None:
    """A type a deployment places in the review journal is held by a
    table the deployment's own script made, found by its key to the
    journal, so the column goes with that fact in its table."""
    upgrade(empty)
    downgrade(empty, "0018")
    labelled = replace(
        entry("labelled-before"),
        event_type="finding.labelled",
        payload={"finding": "f", "verdict": "right"},
    )
    engine = _engine(empty)
    seed_before_keys(
        empty, engine, labelled, run=False, table="review_journal"
    )
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "create table deployment_label ("
                "event_id uuid primary key "
                "references review_journal (event_id), "
                "verdict text not null)"
            )
        )
        connection.execute(
            sa.text(
                "insert into deployment_label (event_id, verdict) "
                "values (:id, 'right')"
            ),
            {"id": labelled.event_id},
        )

    upgrade(empty)

    assert "payload" not in _columns(empty, "review_journal")
    try:
        (row,) = rows(engine, labelled.event_id)
        assert row["payload"] is None
    finally:
        engine.dispose()


def test_the_stocktake_journals_payload_column_goes_once_its_facts_have_tables(
    empty: str,
) -> None:
    """A stocktake fact written before the typed tables is unpacked by
    0015 and loses its payload to 0020: the column is gone from the
    table, the view reads null for it, and the typed row holds the
    fact."""
    upgrade(empty)
    downgrade(empty, "0014")
    graded = replace(
        entry("graded-before"),
        event_type="stocktake.graded",
        payload={
            "layer": "weekly",
            "agent_id": "security",
            "status": "pass",
            "detail": "all well",
        },
    )
    seed_before_keys(
        empty, _engine(empty), graded, run=False, table="stocktake_journal"
    )

    upgrade(empty)

    assert "payload" not in _columns(empty, "stocktake_journal")
    assert "payload" in _columns(empty, "policy_journal")
    engine = _engine(empty)
    try:
        (row,) = rows(engine, graded.event_id)
        assert row["payload"] is None
        with engine.connect() as connection:
            detail = connection.execute(
                sa.text(
                    "select detail from stocktake_grade where event_id = :id"
                ),
                {"id": graded.event_id},
            ).scalar_one()
    finally:
        engine.dispose()
    assert detail == "all well"


def test_a_stocktake_fact_with_no_typed_row_stops_the_column_going(
    empty: str,
) -> None:
    upgrade(empty)
    downgrade(empty, "0019")
    unpacked_by_nothing = replace(
        entry("never-unpacked"),
        event_type="stocktake.graded",
        payload={
            "layer": "weekly",
            "agent_id": "security",
            "status": "pass",
            "detail": "",
        },
    )
    seed_before_keys(
        empty,
        _engine(empty),
        unpacked_by_nothing,
        run=False,
        table="stocktake_journal",
    )

    with pytest.raises(Exception, match=r"1 of type stocktake\.graded"):
        upgrade(empty)


def test_a_deployments_own_table_keyed_to_the_stocktake_journal_holds_its_fact(
    empty: str,
) -> None:
    """A type a deployment places in the stocktake journal is held by a
    table the deployment's own script made, found by its key to the
    journal, so the column goes with that fact in its table."""
    upgrade(empty)
    downgrade(empty, "0019")
    noted = replace(
        entry("noted-before"),
        event_type="stocktake.noted",
        payload={"note": "quiet week"},
    )
    engine = _engine(empty)
    seed_before_keys(
        empty, engine, noted, run=False, table="stocktake_journal"
    )
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "create table deployment_note ("
                "event_id uuid primary key "
                "references stocktake_journal (event_id), "
                "note text not null)"
            )
        )
        connection.execute(
            sa.text(
                "insert into deployment_note (event_id, note) "
                "values (:id, 'quiet week')"
            ),
            {"id": noted.event_id},
        )

    upgrade(empty)

    assert "payload" not in _columns(empty, "stocktake_journal")
    try:
        (row,) = rows(engine, noted.event_id)
        assert row["payload"] is None
    finally:
        engine.dispose()
