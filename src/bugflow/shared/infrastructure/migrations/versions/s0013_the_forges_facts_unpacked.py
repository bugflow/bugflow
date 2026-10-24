"""Unpack the forge's seven facts into tables named for what one row is
(ADR 007), the second journal to be unpacked.

Creates delivery for delivery.received; webhook_reconciliation and
webhook_reconciliation_event for webhook.reconciled;
pull_request_observation with its delivery, component, agent, policy
and commit tables for pr.observed; pull_request_closure and
pull_request_closure_outstanding for pr.closed; pull_request_merge for
pr.merged; reaction and reaction_agent for reaction.recorded; and
finding_dismissal for finding.dismissed, each keyed by the event's id
to the forge journal, and fills them from every row there.

The script stops before it writes if any row's payload has a key the
inventory of 25 October 2026 did not find, lacks one it found on every
row, or holds a nested value of a shape the inventory did not find: a
commit or an outstanding finding with other keys, a list with an
element that is not a string, or a corpus or installed map with a value
that is not a string. No fact is unpacked by guess. The payload column
stays, as the record says, until the journal's last type is unpacked,
which for the forge is this script; it goes by a script of its own.

The downgrade drops the fifteen tables.
"""

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0013"
down_revision = "0012"

#: What each fact's payload holds: the keys every row has, and the keys
#: some rows have. A key outside both stops the script.
REQUIRED = {
    "delivery.received": (
        "delivery_id",
        "event",
        "action",
        "outcome",
        "reason",
    ),
    "webhook.reconciled": ("url", "outcome", "detail", "events"),
    "pr.observed": (
        "snapshot_id",
        "delivery_id",
        "delivery_ids",
        "corpus",
        "title",
        "head_branch",
        "base_branch",
        "author_login",
        "commits",
        "file_count",
        "changed_lines",
    ),
    "pr.closed": ("merged", "outstanding", "reactions"),
    "pr.merged": ("delivery_id",),
    "reaction.recorded": (
        "comment_id",
        "agents",
        "agent_id",
        "evaluated_in",
        "content",
        "login",
        "reacted_at",
    ),
    "finding.dismissed": (
        "policy_id",
        "reason",
        "actor",
        "comment_id",
        "delivery_id",
    ),
}
OPTIONAL: dict[str, tuple[str, ...]] = {
    "delivery.received": (),
    "webhook.reconciled": (),
    # Observations before 26 September 2026 recorded no scope, and
    # before 23 September 2026 no installed agents.
    "pr.observed": ("held", "reviewed_for", "installed"),
    "pr.closed": (),
    "pr.merged": (),
    "reaction.recorded": (),
    "finding.dismissed": (),
}

#: The keys every element of a list of objects has.
ELEMENT_KEYS = {
    ("pr.observed", "commits"): (
        "sha",
        "author_name",
        "author_email",
        "author_login",
        "committer_name",
        "committer_email",
        "committer_login",
        "verified",
        "verification_reason",
    ),
    ("pr.closed", "outstanding"): ("policy_id", "clause", "subject"),
}

#: The lists whose every element is a string.
STRING_LISTS = (
    ("pr.observed", "delivery_ids"),
    ("pr.observed", "held"),
    ("pr.observed", "reviewed_for"),
    ("webhook.reconciled", "events"),
    ("reaction.recorded", "agents"),
)

#: The maps whose every value is a string.
STRING_MAPS = (("pr.observed", "corpus"), ("pr.observed", "installed"))


def _event_id(references: str) -> sa.Column[Any]:
    return sa.Column(
        "event_id",
        PG_UUID(as_uuid=True),
        sa.ForeignKey(f"{references}.event_id"),
        primary_key=True,
    )


def _stop(found: int, event_type: str, what: str) -> None:
    if found:
        raise RuntimeError(
            f"{found} {event_type} rows {what}; read them before unpacking"
        )


def _check_shapes() -> None:
    bind = op.get_bind()
    for event_type, required in REQUIRED.items():
        known = set(required) | set(OPTIONAL[event_type])
        _stop(
            bind.execute(
                sa.text(
                    "SELECT count(*) FROM forge_journal WHERE event_type = :t "
                    "AND jsonb_typeof(payload) <> 'object'"
                ),
                {"t": event_type},
            ).scalar_one(),
            event_type,
            "carry a payload that is not an object",
        )
        found = (
            bind.execute(
                sa.text(
                    "SELECT DISTINCT k FROM (SELECT payload "
                    "FROM forge_journal WHERE event_type = :t) r, "
                    "jsonb_object_keys(r.payload) k"
                ),
                {"t": event_type},
            )
            .scalars()
            .all()
        )
        unknown = sorted(set(found) - known)
        if unknown:
            raise RuntimeError(
                f"{event_type} rows carry keys the inventory did not find: "
                f"{unknown}; read them before unpacking"
            )
        for key in required:
            _stop(
                bind.execute(
                    sa.text(
                        "SELECT count(*) FROM forge_journal "
                        "WHERE event_type = :t AND NOT payload ? :k"
                    ),
                    {"t": event_type, "k": key},
                ).scalar_one(),
                event_type,
                f"lack {key!r}, which every row had at the inventory",
            )
    for (event_type, key), element_keys in ELEMENT_KEYS.items():
        wanted = sorted(element_keys)
        _stop(
            bind.execute(
                sa.text(
                    "SELECT count(DISTINCT j.event_id) FROM forge_journal j, "
                    f"jsonb_array_elements(j.payload->'{key}') e "
                    "WHERE j.event_type = :t AND ("
                    "jsonb_typeof(e) <> 'object' OR "
                    "(SELECT array_agg(k ORDER BY k) "
                    "FROM jsonb_object_keys(e) k) "
                    "IS DISTINCT FROM CAST(:wanted AS text[]))"
                ),
                {"t": event_type, "wanted": wanted},
            ).scalar_one(),
            event_type,
            f"carry a {key} element of a shape the inventory did not find",
        )
    for event_type, key in STRING_LISTS:
        _stop(
            bind.execute(
                sa.text(
                    "SELECT count(DISTINCT j.event_id) FROM forge_journal j, "
                    f"jsonb_array_elements(j.payload->'{key}') e "
                    "WHERE j.event_type = :t AND jsonb_typeof(e) <> 'string'"
                ),
                {"t": event_type},
            ).scalar_one(),
            event_type,
            f"carry a {key} element that is not a string",
        )
    for event_type, key in STRING_MAPS:
        _stop(
            bind.execute(
                sa.text(
                    "SELECT count(DISTINCT j.event_id) FROM forge_journal j, "
                    f"jsonb_each(j.payload->'{key}') kv "
                    "WHERE j.event_type = :t "
                    "AND jsonb_typeof(kv.value) <> 'string'"
                ),
                {"t": event_type},
            ).scalar_one(),
            event_type,
            f"carry a {key} value that is not a string",
        )


def upgrade() -> None:
    _check_shapes()

    op.create_table(
        "delivery",
        _event_id("forge_journal"),
        sa.Column("delivery_id", sa.Text, nullable=False),
        sa.Column("event", sa.Text, nullable=False),
        sa.Column("action", sa.Text),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
    )
    op.create_index("delivery_delivery_id_idx", "delivery", ["delivery_id"])
    op.create_table(
        "webhook_reconciliation",
        _event_id("forge_journal"),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("detail", sa.Text, nullable=False),
    )
    op.create_table(
        "webhook_reconciliation_event",
        _event_id("webhook_reconciliation"),
        sa.Column("event", sa.Text, primary_key=True),
    )
    op.create_table(
        "pull_request_observation",
        _event_id("forge_journal"),
        sa.Column("snapshot_id", sa.Text, nullable=False),
        sa.Column("delivery_id", sa.Text),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("head_branch", sa.Text, nullable=False),
        sa.Column("base_branch", sa.Text, nullable=False),
        sa.Column("author_login", sa.Text, nullable=False),
        sa.Column("file_count", sa.Integer, nullable=False),
        sa.Column("changed_lines", sa.Integer, nullable=False),
    )
    op.create_index(
        "pull_request_observation_snapshot_idx",
        "pull_request_observation",
        ["snapshot_id"],
    )
    op.create_table(
        "pull_request_observation_delivery",
        _event_id("pull_request_observation"),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("delivery_id", sa.Text, nullable=False),
    )
    op.create_table(
        "pull_request_observation_component",
        _event_id("pull_request_observation"),
        sa.Column("component", sa.Text, primary_key=True),
        sa.Column("version", sa.Text, nullable=False),
    )
    op.create_table(
        "pull_request_observation_agent",
        _event_id("pull_request_observation"),
        sa.Column("agent", sa.Text, primary_key=True),
        sa.Column("version", sa.Text, nullable=False),
    )
    op.create_table(
        "pull_request_observation_policy",
        _event_id("pull_request_observation"),
        sa.Column("standing", sa.Text, primary_key=True),
        sa.Column("policy_id", sa.Text, primary_key=True),
    )
    op.create_table(
        "pull_request_observation_commit",
        _event_id("pull_request_observation"),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("sha", sa.Text, nullable=False),
        sa.Column("author_name", sa.Text, nullable=False),
        sa.Column("author_email", sa.Text, nullable=False),
        sa.Column("author_login", sa.Text, nullable=False),
        sa.Column("committer_name", sa.Text, nullable=False),
        sa.Column("committer_email", sa.Text, nullable=False),
        sa.Column("committer_login", sa.Text, nullable=False),
        sa.Column("verified", sa.Boolean, nullable=False),
        sa.Column("verification_reason", sa.Text, nullable=False),
    )
    op.create_table(
        "pull_request_closure",
        _event_id("forge_journal"),
        sa.Column("merged", sa.Boolean, nullable=False),
        sa.Column("reactions", sa.Integer, nullable=False),
    )
    op.create_table(
        "pull_request_closure_outstanding",
        _event_id("pull_request_closure"),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("policy_id", sa.Text, nullable=False),
        sa.Column("clause", sa.Text, nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
    )
    op.create_table(
        "pull_request_merge",
        _event_id("forge_journal"),
        sa.Column("delivery_id", sa.Text, nullable=False),
    )
    op.create_table(
        "reaction",
        _event_id("forge_journal"),
        sa.Column("comment_id", sa.BigInteger, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("login", sa.Text, nullable=False),
        sa.Column("reacted_at", sa.DateTime(timezone=True)),
        sa.Column("agent_id", sa.Text),
        sa.Column("evaluated_in", sa.Text, nullable=False),
    )
    op.create_table(
        "reaction_agent",
        _event_id("reaction"),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("agent_id", sa.Text, nullable=False),
    )
    op.create_table(
        "finding_dismissal",
        _event_id("forge_journal"),
        sa.Column("policy_id", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("actor", sa.Text),
        sa.Column("comment_id", sa.BigInteger, nullable=False),
        sa.Column("delivery_id", sa.Text, nullable=False),
    )

    op.execute(
        """
        INSERT INTO delivery (event_id, delivery_id, event, action, outcome,
                              reason)
        SELECT event_id, payload->>'delivery_id', payload->>'event',
               payload->>'action', payload->>'outcome', payload->>'reason'
        FROM forge_journal WHERE event_type = 'delivery.received'
        """
    )
    op.execute(
        """
        INSERT INTO webhook_reconciliation (event_id, url, outcome, detail)
        SELECT event_id, payload->>'url', payload->>'outcome',
               payload->>'detail'
        FROM forge_journal WHERE event_type = 'webhook.reconciled'
        """
    )
    op.execute(
        """
        INSERT INTO webhook_reconciliation_event (event_id, event)
        SELECT DISTINCT j.event_id, e
        FROM forge_journal j, jsonb_array_elements_text(j.payload->'events') e
        WHERE j.event_type = 'webhook.reconciled'
        """
    )
    op.execute(
        """
        INSERT INTO pull_request_observation (event_id, snapshot_id,
            delivery_id, title, head_branch, base_branch, author_login,
            file_count, changed_lines)
        SELECT event_id, payload->>'snapshot_id', payload->>'delivery_id',
               payload->>'title', payload->>'head_branch',
               payload->>'base_branch', payload->>'author_login',
               (payload->>'file_count')::integer,
               (payload->>'changed_lines')::integer
        FROM forge_journal WHERE event_type = 'pr.observed'
        """
    )
    op.execute(
        """
        INSERT INTO pull_request_observation_delivery (event_id, position,
                                                       delivery_id)
        SELECT j.event_id, d.ordinality - 1, d.value
        FROM forge_journal j,
             jsonb_array_elements_text(j.payload->'delivery_ids')
                 WITH ORDINALITY d
        WHERE j.event_type = 'pr.observed'
        """
    )
    op.execute(
        """
        INSERT INTO pull_request_observation_component (event_id, component,
                                                        version)
        SELECT j.event_id, c.key, c.value
        FROM forge_journal j, jsonb_each_text(j.payload->'corpus') c
        WHERE j.event_type = 'pr.observed'
        """
    )
    op.execute(
        """
        INSERT INTO pull_request_observation_agent (event_id, agent, version)
        SELECT j.event_id, a.key, a.value
        FROM forge_journal j, jsonb_each_text(j.payload->'installed') a
        WHERE j.event_type = 'pr.observed'
        """
    )
    op.execute(
        """
        INSERT INTO pull_request_observation_policy (event_id, standing,
                                                     policy_id)
        SELECT DISTINCT j.event_id, s.standing, p
        FROM forge_journal j,
             (VALUES ('reviewed_for'), ('held')) AS s(standing),
             jsonb_array_elements_text(j.payload->s.standing) p
        WHERE j.event_type = 'pr.observed'
        """
    )
    op.execute(
        """
        INSERT INTO pull_request_observation_commit (event_id, position, sha,
            author_name, author_email, author_login, committer_name,
            committer_email, committer_login, verified, verification_reason)
        SELECT j.event_id, c.ordinality - 1, c.value->>'sha',
               c.value->>'author_name', c.value->>'author_email',
               c.value->>'author_login', c.value->>'committer_name',
               c.value->>'committer_email', c.value->>'committer_login',
               (c.value->>'verified')::boolean,
               c.value->>'verification_reason'
        FROM forge_journal j,
             jsonb_array_elements(j.payload->'commits') WITH ORDINALITY c
        WHERE j.event_type = 'pr.observed'
        """
    )
    op.execute(
        """
        INSERT INTO pull_request_closure (event_id, merged, reactions)
        SELECT event_id, (payload->>'merged')::boolean,
               (payload->>'reactions')::integer
        FROM forge_journal WHERE event_type = 'pr.closed'
        """
    )
    op.execute(
        """
        INSERT INTO pull_request_closure_outstanding (event_id, position,
            policy_id, clause, subject)
        SELECT j.event_id, f.ordinality - 1, f.value->>'policy_id',
               f.value->>'clause', f.value->>'subject'
        FROM forge_journal j,
             jsonb_array_elements(j.payload->'outstanding') WITH ORDINALITY f
        WHERE j.event_type = 'pr.closed'
        """
    )
    op.execute(
        """
        INSERT INTO pull_request_merge (event_id, delivery_id)
        SELECT event_id, payload->>'delivery_id'
        FROM forge_journal WHERE event_type = 'pr.merged'
        """
    )
    op.execute(
        """
        INSERT INTO reaction (event_id, comment_id, content, login,
                              reacted_at, agent_id, evaluated_in)
        SELECT event_id, (payload->>'comment_id')::bigint, payload->>'content',
               payload->>'login', (payload->>'reacted_at')::timestamptz,
               payload->>'agent_id', payload->>'evaluated_in'
        FROM forge_journal WHERE event_type = 'reaction.recorded'
        """
    )
    op.execute(
        """
        INSERT INTO reaction_agent (event_id, position, agent_id)
        SELECT j.event_id, a.ordinality - 1, a.value
        FROM forge_journal j,
             jsonb_array_elements_text(j.payload->'agents') WITH ORDINALITY a
        WHERE j.event_type = 'reaction.recorded'
        """
    )
    op.execute(
        """
        INSERT INTO finding_dismissal (event_id, policy_id, reason, actor,
                                       comment_id, delivery_id)
        SELECT event_id, payload->>'policy_id', payload->>'reason',
               payload->>'actor', (payload->>'comment_id')::bigint,
               payload->>'delivery_id'
        FROM forge_journal WHERE event_type = 'finding.dismissed'
        """
    )


def downgrade() -> None:
    for table in (
        "finding_dismissal",
        "reaction_agent",
        "reaction",
        "pull_request_merge",
        "pull_request_closure_outstanding",
        "pull_request_closure",
        "pull_request_observation_commit",
        "pull_request_observation_policy",
        "pull_request_observation_agent",
        "pull_request_observation_component",
        "pull_request_observation_delivery",
        "pull_request_observation",
        "webhook_reconciliation_event",
        "webhook_reconciliation",
        "delivery",
    ):
        op.drop_table(table)
