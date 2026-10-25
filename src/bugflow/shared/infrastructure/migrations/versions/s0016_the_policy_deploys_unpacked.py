"""Unpack the policy journal's deploys into a table named for what one
row is (ADR 007), the fifth journal to be unpacked.

Creates policy_deploy for policies.deployed, keyed by the event's id to
the policy journal, and fills it from every row there. The deployment
replaced, an object in the payload or null for the server's first
deploy, is flattened into three prefixed columns.

The journal's other type, policy.calibrated, is written by a deployment
and not by the package, so its payload is that deployment's to unpack,
and this script leaves its rows as they are.

The check stops on a payload that is not an object, a key outside the
inventory of 25 October 2026 at the top level or inside the replaced
deployment, and a replaced deployment that is neither an object nor
null. No fact is unpacked by guess. The payload column stays until the
journal's last type is unpacked.

The downgrade drops the table.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0016"
down_revision = "0015"

EVENT_TYPE = "policies.deployed"

#: The keys every deploy has. The inventory found no optional key.
REQUIRED = (
    "repository",
    "commit",
    "content_hash",
    "files",
    "sent_by",
    "replaced",
)

#: The keys the replaced deployment has, where it is an object.
REPLACED_KEYS = ("repository", "commit", "content_hash")


def _stop(found: int, what: str) -> None:
    if found:
        raise RuntimeError(
            f"{found} {EVENT_TYPE} rows {what}; read them before unpacking"
        )


def _count(sql: str, **params: object) -> int:
    return int(
        op.get_bind()
        .execute(sa.text(sql), {"t": EVENT_TYPE, **params})
        .scalar_one()
    )


def _check_shapes() -> None:
    _stop(
        _count(
            "SELECT count(*) FROM policy_journal WHERE event_type = :t "
            "AND jsonb_typeof(payload) <> 'object'"
        ),
        "carry a payload that is not an object",
    )
    _stop(
        _count(
            "SELECT count(*) FROM policy_journal WHERE event_type = :t "
            "AND NOT (SELECT coalesce(array_agg(k), '{}') "
            "FROM jsonb_object_keys(payload) k) <@ CAST(:known AS text[])",
            known=sorted(REQUIRED),
        ),
        "carry keys the inventory did not find",
    )
    for key in REQUIRED:
        _stop(
            _count(
                "SELECT count(*) FROM policy_journal WHERE event_type = :t "
                "AND NOT payload ? :k",
                k=key,
            ),
            f"lack {key!r}, which every such row had at the inventory",
        )
    _stop(
        _count(
            "SELECT count(*) FROM policy_journal WHERE event_type = :t "
            "AND jsonb_typeof(payload->'replaced') NOT IN ('object', 'null')"
        ),
        "carry a replaced deployment that is not an object",
    )
    _stop(
        _count(
            "SELECT count(*) FROM policy_journal WHERE event_type = :t "
            "AND jsonb_typeof(payload->'replaced') = 'object' AND "
            "(SELECT array_agg(k ORDER BY k) "
            "FROM jsonb_object_keys(payload->'replaced') k)"
            " IS DISTINCT FROM CAST(:wanted AS text[])",
            wanted=sorted(REPLACED_KEYS),
        ),
        "carry a replaced deployment of a shape the inventory did not find",
    )


def upgrade() -> None:
    _check_shapes()

    op.create_table(
        "policy_deploy",
        sa.Column(
            "event_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("policy_journal.event_id"),
            primary_key=True,
        ),
        sa.Column("repository", sa.Text, nullable=False),
        sa.Column("commit", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("files", sa.Integer, nullable=False),
        sa.Column("sent_by", sa.Text, nullable=False),
        sa.Column("replaced_repository", sa.Text),
        sa.Column("replaced_commit", sa.Text),
        sa.Column("replaced_content_hash", sa.Text),
    )
    op.create_index(
        "policy_deploy_commit_idx", "policy_deploy", ["repository", "commit"]
    )
    op.execute(
        """
        INSERT INTO policy_deploy (event_id, repository, commit, content_hash,
            files, sent_by, replaced_repository, replaced_commit,
            replaced_content_hash)
        SELECT event_id, payload->>'repository', payload->>'commit',
               payload->>'content_hash', (payload->>'files')::integer,
               payload->>'sent_by', payload->'replaced'->>'repository',
               payload->'replaced'->>'commit',
               payload->'replaced'->>'content_hash'
        FROM policy_journal WHERE event_type = 'policies.deployed'
        """
    )


def downgrade() -> None:
    op.drop_table("policy_deploy")
