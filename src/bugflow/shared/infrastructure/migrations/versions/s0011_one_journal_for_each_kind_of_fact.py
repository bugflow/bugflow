"""Divide the journal into one table for each kind of fact, and leave
``journal`` as a view over them (ADR 006).

Creates archive_journal, forge_journal, review_journal,
stocktake_journal and policy_journal, each of the journal's shape with
its indexes under its own name and the journal's two triggers, copies
each kind's rows into its own by the event type, drops the journal
table and creates the view in its name, with the columns the table had.
The script stops before it copies if any row has an event type no
journal is named for, so a fact nobody placed is never lost.

A view a deployment built over the journal table, as PMI's
real_journal is, is dropped with it, and the deployment's branch
creates it again over the view, by a script that depends on this one.

The downgrade creates the table again, copies every row back, and drops
the view and the five, and a deployment's view over the view with them.

The programs are stopped while this runs, as for the renames.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.schema import SchemaItem

revision = "0011"
down_revision = "0010"

#: The event types of each kind, as the shared kernel's map has them. A
#: script states what it does and imports nothing from the package.
KINDS = {
    "archive": ("archive.sealed", "archive.bound", "archive.refused"),
    "forge": (
        "delivery.received",
        "webhook.reconciled",
        "pr.observed",
        "pr.closed",
        "pr.merged",
        "reaction.recorded",
        "finding.dismissed",
    ),
    "review": (
        "agent.dispatched",
        "completion.received",
        "review.graded",
        "judge.invoked",
        "llm.called",
        "policy.checked",
        "finding.raised",
        "finding.resolved",
        "finding.rewritten",
        "finding.withheld",
        "action.taken",
    ),
    "stocktake": (
        "stocktake.taken",
        "stocktake.dispatched",
        "stocktake.reviewed",
        "stocktake.found",
        "stocktake.graded",
    ),
    "policy": ("policies.deployed", "policy.calibrated"),
}

COLUMNS = (
    "event_id",
    "occurred_at",
    "recorded_at",
    "event_type",
    "forge",
    "repo",
    "pr_number",
    "commit_sha",
    "corpus_version",
    "workflow_id",
    "run_id",
    "payload",
    "agent_id",
    "build",
    "policy_repository",
    "policy_commit",
    "policy_content",
    "pull_request_id",
    "workflow_run_id",
)


def _columns() -> list[SchemaItem]:
    return [
        sa.Column("event_id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("forge", sa.Text, nullable=False),
        sa.Column("repo", sa.Text, nullable=False),
        sa.Column("pr_number", sa.Integer),
        sa.Column("commit_sha", sa.Text),
        sa.Column("corpus_version", sa.Text),
        sa.Column("workflow_id", sa.Text, nullable=False),
        sa.Column("run_id", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("agent_id", sa.Text),
        sa.Column("build", sa.Text),
        sa.Column("policy_repository", sa.Text),
        sa.Column("policy_commit", sa.Text),
        sa.Column("policy_content", sa.Text),
        sa.Column(
            "pull_request_id", sa.BigInteger, sa.ForeignKey("pull_request.id")
        ),
        sa.Column(
            "workflow_run_id", sa.BigInteger, sa.ForeignKey("workflow_run.id")
        ),
    ]


def _indexes(name: str) -> list[tuple[str, list[str]]]:
    return [
        (f"{name}_repo_pr_occurred", ["repo", "pr_number", "occurred_at"]),
        (f"{name}_pull_request_occurred", ["pull_request_id", "occurred_at"]),
        (f"{name}_workflow_run", ["workflow_run_id"]),
        (f"{name}_type_occurred", ["event_type", "occurred_at"]),
        (f"{name}_run", ["workflow_id", "run_id"]),
        (f"{name}_agent_id_idx", ["agent_id", "corpus_version"]),
        (f"{name}_build_idx", ["build", "occurred_at"]),
        (
            f"{name}_policy_deployment_idx",
            ["policy_repository", "policy_commit", "occurred_at"],
        ),
    ]


def _make_journal(name: str) -> None:
    op.create_table(name, *_columns())
    for index, columns in _indexes(name):
        op.create_index(index, name, columns)
    op.execute(
        f"CREATE TRIGGER {name}_append_only "
        f"BEFORE UPDATE OR DELETE ON {name} "
        "FOR EACH ROW EXECUTE FUNCTION journal_reject_change()"
    )
    op.execute(
        f"CREATE TRIGGER {name}_no_truncate "
        f"BEFORE TRUNCATE ON {name} "
        "FOR EACH STATEMENT EXECUTE FUNCTION journal_reject_change()"
    )


def _quoted(types: tuple[str, ...]) -> str:
    return ", ".join(f"'{event_type}'" for event_type in types)


def upgrade() -> None:
    placed = _quoted(tuple(t for types in KINDS.values() for t in types))
    unplaced = (
        op.get_bind()
        .execute(
            sa.text(
                f"SELECT DISTINCT event_type FROM journal "
                f"WHERE event_type NOT IN ({placed})"
            )
        )
        .scalars()
        .all()
    )
    if unplaced:
        raise RuntimeError(
            f"no journal is named for {sorted(unplaced)}; add each to the "
            "map in the shared kernel and to this script before it runs"
        )
    columns = ", ".join(COLUMNS)
    for kind, types in KINDS.items():
        name = f"{kind}_journal"
        _make_journal(name)
        op.execute(
            f"INSERT INTO {name} ({columns}) SELECT {columns} FROM journal "
            f"WHERE event_type IN ({_quoted(types)})"
        )
    # A view a deployment built over the table, as PMI's real_journal is,
    # goes with it, and the deployment's own script that depends on this
    # one creates it again over the view below.
    op.execute("DROP TABLE journal CASCADE")
    op.execute(
        "CREATE VIEW journal AS "
        + " UNION ALL ".join(
            f"SELECT {columns} FROM {kind}_journal" for kind in KINDS
        )
    )


def downgrade() -> None:
    columns = ", ".join(COLUMNS)
    op.execute("DROP VIEW journal CASCADE")
    _make_journal("journal")
    for kind in KINDS:
        op.execute(
            f"INSERT INTO journal ({columns}) "
            f"SELECT {columns} FROM {kind}_journal"
        )
        op.drop_table(f"{kind}_journal")
