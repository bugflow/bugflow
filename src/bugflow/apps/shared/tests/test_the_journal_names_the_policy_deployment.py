"""Each row the stamped journal writes names the policy deployment its
program started with, against the real database.

The three values are columns of the journal table and are not fields
of a journal entry, so these tests read the table.

Skipped unless DATABASE_URL names a Postgres server.
"""

import sqlalchemy as sa

from bugflow.apps.shared.journals import review_journal, stamped_journal
from bugflow.apps.shared.tests.test_the_journal_names_its_build import (
    BUILD,
    entry,
    new_run,
)
from bugflow.method.infrastructure.deployment_watch import DeployedFrom
from bugflow.shared.domain.values.correlation import Correlation

DEPLOYED = DeployedFrom(
    repository="example-org/pull-request-policies",
    commit="c" * 40,
    content_hash="h" * 64,
)


def stamps(engine: sa.Engine, run: Correlation) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                sa.text(
                    "select policy_repository, policy_commit, policy_content "
                    "from journal where run_id = :run"
                ),
                {"run": run.run_id},
            )
        ]


def test_a_row_names_the_deployment_its_journal_was_given(
    engine: sa.Engine, database_url: str
) -> None:
    run = new_run()
    stamped_journal(database_url, None, DEPLOYED).append([entry(run)])
    assert stamps(engine, run) == [
        (DEPLOYED.repository, DEPLOYED.commit, DEPLOYED.content_hash)
    ]


def test_a_journal_given_no_deployment_leaves_the_columns_empty(
    engine: sa.Engine, database_url: str
) -> None:
    run = new_run()
    stamped_journal(database_url, BUILD).append([entry(run)])
    assert stamps(engine, run) == [(None, None, None)]


def test_the_build_is_still_stamped_beside_the_deployment(
    engine: sa.Engine, database_url: str
) -> None:
    run = new_run()
    journal = review_journal(database_url, BUILD, DEPLOYED)
    journal.append([entry(run)])
    assert [e.build for e in journal.entries_for_run(run)] == [BUILD]
    assert stamps(engine, run) == [
        (DEPLOYED.repository, DEPLOYED.commit, DEPLOYED.content_hash)
    ]


def test_the_columns_are_indexed_together(engine: sa.Engine) -> None:
    indexes = {
        index["name"]: index["column_names"]
        for index in sa.inspect(engine).get_indexes("journal")
    }
    assert indexes["journal_policy_deployment_idx"] == [
        "policy_repository",
        "policy_commit",
        "occurred_at",
    ]
