"""Unpack the review's facts into tables named for what one row is (ADR
007), the third journal to be unpacked.

Creates review_action and review_action_removed_label for action.taken;
agent_dispatch and agent_dispatch_withheld_file for agent.dispatched;
raised_finding, resolved_finding, rewritten_finding and withheld_finding
for the four finding facts; judge_invocation and
judge_invocation_unsupported for judge.invoked; model_call,
model_call_finish_reason and model_call_object for llm.called;
policy_check for policy.checked; review_grade for review.graded; and
completion for completion.received, the work context's fact placed in
this journal. Each is keyed by the event's id to the review journal,
and the script fills them from every row there.

An action's and a dispatch's keys depend on the action or the step, so
the check reads each row against the keys its action or step had at
the inventory of 25 October 2026, and stops on an action or a step the
inventory did not find. It stops too on a key outside the inventory at
the top level or inside a judge identity, a budget, a cost or a stored
object, on a list element that is not a string, on a cost that is not a
decimal and on a time that is not ISO 8601. No fact is unpacked by
guess. The payload column stays until the journal's last type is
unpacked; a deployment's own types placed in this journal keep theirs.

The downgrade drops the sixteen tables.
"""

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0014"
down_revision = "0013"

#: What each fact's payload holds: the keys every row has, and the keys
#: some rows have. A key outside both stops the script.
REQUIRED: dict[str, tuple[str, ...]] = {
    "finding.raised": (
        "policy_id",
        "severity",
        "clause",
        "subject",
        "message",
        "judged_by",
        "judge",
        "corpus_version",
    ),
    "finding.resolved": (
        "policy_id",
        "severity",
        "clause",
        "subject",
        "message",
        "judged_by",
        "judge",
        "corpus_version",
        "raised_in_workflow_id",
        "raised_in_run_id",
    ),
    "finding.rewritten": (
        "policy_id",
        "severity",
        "clause",
        "subject",
        "message",
        "judged_by",
        "judge",
        "corpus_version",
        "raised_in_workflow_id",
        "raised_in_run_id",
    ),
    "finding.withheld": (
        "policy_id",
        "severity",
        "clause",
        "subject",
        "message",
        "judged_by",
        "judge",
        "corpus_version",
        "share",
    ),
    "judge.invoked": (
        "policy_id",
        "status",
        "model",
        "finding_count",
        "unsupported",
        "input_tokens",
        "output_tokens",
        "identity",
    ),
    "llm.called": (
        "call_id",
        "purpose",
        "policy_id",
        "status",
        "http_status",
        "error",
        "requested_model",
        "answered_model",
        "model_id",
        "model_group",
        "api_base",
        "proxy_version",
        "attempt",
        "retries",
        "fallbacks",
        "finish_reasons",
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "reasoning_output_tokens",
        "total_tokens",
        "cost_usd",
        "cost_nanodollars",
        "cost_input_usd",
        "cost_output_usd",
        "cost_cache_read_usd",
        "cost_cache_creation_usd",
        "cost_reasoning_usd",
        "started_at",
        "ended_at",
        "client_duration_ms",
        "provider_duration_ms",
        "proxy_overhead_ms",
        "trace_id",
        "span_id",
        "objects",
    ),
    "policy.checked": ("policy_id", "clause", "finding_count"),
    "review.graded": ("agent_id", "status", "detail"),
    "completion.received": ("runner", "remote_id", "outcome", "reason"),
}
OPTIONAL: dict[str, tuple[str, ...]] = {
    # Findings before 23 September 2026 named no agent.
    "finding.raised": ("agent_id",),
    "finding.resolved": ("agent_id",),
    "finding.rewritten": ("agent_id",),
    "finding.withheld": ("agent_id",),
    "judge.invoked": (),
    # Calls before 18 September 2026 named no archive folder, and
    # before 19 September 2026 no cache creation tokens.
    "llm.called": ("archive_folder", "cache_creation_input_tokens"),
    # Checks before 26 September 2026 recorded no cost.
    "policy.checked": ("cost",),
    "review.graded": (),
    "completion.received": (),
}

#: The keys each kind of action carries, by its ``action``. A summary
#: comment was written before 19 September 2026.
ACTION_KEYS: dict[str, tuple[str, ...]] = {
    "review_comment": (
        "action",
        "agent_id",
        "performed",
        "status",
        "comment_id",
        "verdict",
        "head_sha",
        "finding_count",
        "raised_count",
        "fixed_count",
        "dismissed_count",
    ),
    "commit_status": (
        "action",
        "performed",
        "status",
        "context",
        "state",
        "description",
    ),
    "outcome_label": ("action", "performed", "status", "label", "removed"),
    "summary_comment": (
        "action",
        "performed",
        "status",
        "comment_id",
        "finding_count",
        "raised_count",
        "fixed_count",
        "dismissed_count",
    ),
}
#: A commit status before 19 September 2026 named no agent.
ACTION_OPTIONAL: dict[str, tuple[str, ...]] = {"commit_status": ("agent_id",)}

#: The keys each step of a dispatch carries, by its ``step``: the three
#: steps the inventory found, and the four the code writes for a run
#: that did not start.
STEP_KEYS: dict[str, tuple[str, ...]] = {
    "dispatched": (
        "agent_id",
        "step",
        "runner",
        "fingerprint",
        "remote_id",
        "budget",
        "withheld",
    ),
    "collected": (
        "agent_id",
        "step",
        "outcome",
        "runner",
        "fingerprint",
        "cost",
        "events",
        "detail",
    ),
    "recovered": (
        "agent_id",
        "step",
        "runner",
        "remote_id",
        "write_up_id",
        "outcome",
        "dispatched_at",
    ),
    "refused": ("agent_id", "step", "reason"),
    "reused": ("agent_id", "step", "fingerprint", "reviewed_in"),
    "no-worktree": ("agent_id", "step", "reason"),
    "unavailable": ("agent_id", "step", "reason"),
}
#: A collected run stored its write-up only from 23 September 2026.
STEP_OPTIONAL: dict[str, tuple[str, ...]] = {"collected": ("write_up_id",)}

#: The keys an object inside a payload has, where the object is there.
OBJECT_KEYS = {
    ("finding.raised", "judge"): (
        "model",
        "fingerprint",
        "prompt_hash",
        "input_hash",
        "exchange_id",
    ),
    ("finding.resolved", "judge"): (
        "model",
        "fingerprint",
        "prompt_hash",
        "input_hash",
        "exchange_id",
    ),
    ("finding.rewritten", "judge"): (
        "model",
        "fingerprint",
        "prompt_hash",
        "input_hash",
        "exchange_id",
    ),
    ("finding.withheld", "judge"): (
        "model",
        "fingerprint",
        "prompt_hash",
        "input_hash",
        "exchange_id",
    ),
    ("judge.invoked", "identity"): (
        "model",
        "fingerprint",
        "prompt_hash",
        "input_hash",
        "exchange_id",
    ),
    ("agent.dispatched", "budget"): ("usd", "turns"),
    ("agent.dispatched", "cost"): ("usd", "seconds"),
    ("policy.checked", "cost"): ("usd",),
}

#: The keys every element of a list of objects has.
ELEMENT_KEYS = {
    ("llm.called", "objects"): ("hop", "key", "sha256", "bytes", "encoding"),
}

#: The lists whose every element is a string.
STRING_LISTS = (
    ("action.taken", "removed"),
    ("agent.dispatched", "withheld"),
    ("judge.invoked", "unsupported"),
    ("llm.called", "finish_reasons"),
)

#: The strings that are decimals, where they are strings.
DECIMALS = (
    ("llm.called", "cost_usd"),
    ("llm.called", "cost_input_usd"),
    ("llm.called", "cost_output_usd"),
    ("llm.called", "cost_cache_read_usd"),
    ("llm.called", "cost_cache_creation_usd"),
    ("llm.called", "cost_reasoning_usd"),
)

#: The strings that are times, where they are strings.
TIMES = (
    ("llm.called", "started_at"),
    ("llm.called", "ended_at"),
    ("agent.dispatched", "dispatched_at"),
)

DECIMAL = r"^-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?$"
ISO = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"


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


def _count(sql: str, **params: object) -> int:
    return int(op.get_bind().execute(sa.text(sql), params).scalar_one())


def _check_keys(
    event_type: str,
    required: tuple[str, ...],
    optional: tuple[str, ...],
    where: str = "",
    **params: object,
) -> None:
    """Stop on a row of the type, narrowed by ``where``, whose keys lie
    outside the known set or lack a required one."""
    known = sorted(set(required) | set(optional))
    _stop(
        _count(
            "SELECT count(*) FROM review_journal WHERE event_type = :t "
            f"{where} AND NOT (SELECT coalesce(array_agg(k), '{{}}') "
            "FROM jsonb_object_keys(payload) k) <@ CAST(:known AS text[])",
            t=event_type,
            known=known,
            **params,
        ),
        event_type,
        f"carry keys the inventory did not find{where and ' for ' + where}",
    )
    for key in required:
        _stop(
            _count(
                "SELECT count(*) FROM review_journal WHERE event_type = :t "
                f"{where} AND NOT payload ? :k",
                t=event_type,
                k=key,
                **params,
            ),
            event_type,
            f"lack {key!r}, which every such row had at the inventory",
        )


def _check_shapes() -> None:
    types = (
        "action.taken",
        "agent.dispatched",
        *REQUIRED,
    )
    for event_type in types:
        _stop(
            _count(
                "SELECT count(*) FROM review_journal WHERE event_type = :t "
                "AND jsonb_typeof(payload) <> 'object'",
                t=event_type,
            ),
            event_type,
            "carry a payload that is not an object",
        )
    for event_type, required in REQUIRED.items():
        _check_keys(event_type, required, OPTIONAL[event_type])
    for kind, column, keys, optional in (
        ("action.taken", "action", ACTION_KEYS, ACTION_OPTIONAL),
        ("agent.dispatched", "step", STEP_KEYS, STEP_OPTIONAL),
    ):
        _stop(
            _count(
                "SELECT count(*) FROM review_journal WHERE event_type = :t "
                f"AND NOT payload->>'{column}' = ANY(CAST(:kinds AS text[]))",
                t=kind,
                kinds=sorted(keys),
            ),
            kind,
            f"carry a kind of {column} the inventory did not find",
        )
        for value, required in keys.items():
            _check_keys(
                kind,
                required,
                optional.get(value, ()),
                where=f"AND payload->>'{column}' = :v",
                v=value,
            )
    for (event_type, key), object_keys in OBJECT_KEYS.items():
        _stop(
            _count(
                "SELECT count(*) FROM review_journal WHERE event_type = :t "
                f"AND payload ? '{key}' AND jsonb_typeof(payload->'{key}') "
                "NOT IN ('object', 'null')",
                t=event_type,
            ),
            event_type,
            f"carry a {key} that is not an object",
        )
        _stop(
            _count(
                "SELECT count(*) FROM review_journal WHERE event_type = :t "
                f"AND jsonb_typeof(payload->'{key}') = 'object' AND "
                "(SELECT array_agg(k ORDER BY k) "
                f"FROM jsonb_object_keys(payload->'{key}') k)"
                " IS DISTINCT FROM CAST(:wanted AS text[])",
                t=event_type,
                wanted=sorted(object_keys),
            ),
            event_type,
            f"carry a {key} of a shape the inventory did not find",
        )
    for (event_type, key), element_keys in ELEMENT_KEYS.items():
        _stop(
            _count(
                "SELECT count(DISTINCT j.event_id) FROM review_journal j, "
                f"jsonb_array_elements(j.payload->'{key}') e "
                "WHERE j.event_type = :t AND (jsonb_typeof(e) <> 'object' OR "
                "(SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(e) k) "
                "IS DISTINCT FROM CAST(:wanted AS text[]))",
                t=event_type,
                wanted=sorted(element_keys),
            ),
            event_type,
            f"carry a {key} element of a shape the inventory did not find",
        )
    for event_type, key in STRING_LISTS:
        _stop(
            _count(
                "SELECT count(DISTINCT j.event_id) FROM review_journal j, "
                f"jsonb_array_elements(j.payload->'{key}') e "
                "WHERE j.event_type = :t AND jsonb_typeof(e) <> 'string'",
                t=event_type,
            ),
            event_type,
            f"carry a {key} element that is not a string",
        )
    for event_type, key in DECIMALS:
        _stop(
            _count(
                "SELECT count(*) FROM review_journal WHERE event_type = :t "
                f"AND jsonb_typeof(payload->'{key}') = 'string' "
                f"AND NOT (payload->>'{key}') ~ :pattern",
                t=event_type,
                pattern=DECIMAL,
            ),
            event_type,
            f"carry a {key} that is not a decimal",
        )
    for event_type, key in TIMES:
        _stop(
            _count(
                "SELECT count(*) FROM review_journal WHERE event_type = :t "
                f"AND jsonb_typeof(payload->'{key}') = 'string' "
                f"AND NOT (payload->>'{key}') ~ :pattern",
                t=event_type,
                pattern=ISO,
            ),
            event_type,
            f"carry a {key} that is not a time",
        )


def _finding_columns() -> list[Any]:
    return [
        sa.Column("policy_id", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("clause", sa.Text, nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("judged_by", sa.Text),
        sa.Column("judge_model", sa.Text),
        sa.Column("judge_fingerprint", sa.Text),
        sa.Column("judge_prompt_hash", sa.Text),
        sa.Column("judge_input_hash", sa.Text),
        sa.Column("judge_exchange_id", sa.Text),
        sa.Column("corpus_version", sa.Text),
        sa.Column("agent_id", sa.Text),
    ]


def _raised_in() -> list[Any]:
    return [
        sa.Column("raised_in_workflow_id", sa.Text, nullable=False),
        sa.Column("raised_in_run_id", sa.Text, nullable=False),
    ]


FINDING_SELECT = """
    payload->>'policy_id', payload->>'severity', payload->>'clause',
    payload->>'subject', payload->>'message', payload->>'judged_by',
    payload->'judge'->>'model', payload->'judge'->>'fingerprint',
    payload->'judge'->>'prompt_hash', payload->'judge'->>'input_hash',
    payload->'judge'->>'exchange_id', payload->>'corpus_version',
    payload->>'agent_id'
"""
FINDING_COLUMNS = """
    policy_id, severity, clause, subject, message, judged_by, judge_model,
    judge_fingerprint, judge_prompt_hash, judge_input_hash,
    judge_exchange_id, corpus_version, agent_id
"""


def upgrade() -> None:
    _check_shapes()

    op.create_table(
        "review_action",
        _event_id("review_journal"),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("performed", sa.Boolean, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("agent_id", sa.Text),
        sa.Column("comment_id", sa.BigInteger),
        sa.Column("verdict", sa.Text),
        sa.Column("head_sha", sa.Text),
        sa.Column("finding_count", sa.Integer),
        sa.Column("raised_count", sa.Integer),
        sa.Column("fixed_count", sa.Integer),
        sa.Column("dismissed_count", sa.Integer),
        sa.Column("context", sa.Text),
        sa.Column("state", sa.Text),
        sa.Column("description", sa.Text),
        sa.Column("label", sa.Text),
    )
    op.create_index("review_action_action_idx", "review_action", ["action"])
    op.create_table(
        "review_action_removed_label",
        _event_id("review_action"),
        sa.Column("label", sa.Text, primary_key=True),
    )
    op.create_table(
        "agent_dispatch",
        _event_id("review_journal"),
        sa.Column("agent_id", sa.Text, nullable=False),
        sa.Column("step", sa.Text, nullable=False),
        sa.Column("runner", sa.Text),
        sa.Column("fingerprint", sa.Text),
        sa.Column("remote_id", sa.Text),
        sa.Column("budget_usd", sa.Float),
        sa.Column("budget_turns", sa.Float),
        sa.Column("cost_usd", sa.Float),
        sa.Column("cost_seconds", sa.Float),
        sa.Column("events", sa.Integer),
        sa.Column("detail", sa.Text),
        sa.Column("outcome", sa.Text),
        sa.Column("write_up_id", sa.Text),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("reason", sa.Text),
        sa.Column("reviewed_in", sa.Text),
    )
    op.create_index("agent_dispatch_step_idx", "agent_dispatch", ["step"])
    op.create_table(
        "agent_dispatch_withheld_file",
        _event_id("agent_dispatch"),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("path", sa.Text, nullable=False),
    )
    op.create_table(
        "raised_finding", _event_id("review_journal"), *_finding_columns()
    )
    op.create_index(
        "raised_finding_policy_idx", "raised_finding", ["policy_id"]
    )
    op.create_table(
        "resolved_finding",
        _event_id("review_journal"),
        *_finding_columns(),
        *_raised_in(),
    )
    op.create_table(
        "rewritten_finding",
        _event_id("review_journal"),
        *_finding_columns(),
        *_raised_in(),
    )
    op.create_table(
        "withheld_finding",
        _event_id("review_journal"),
        *_finding_columns(),
        sa.Column("share", sa.Float, nullable=False),
    )
    op.create_table(
        "judge_invocation",
        _event_id("review_journal"),
        sa.Column("policy_id", sa.Text),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("model", sa.Text),
        sa.Column("finding_count", sa.Integer, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("identity_model", sa.Text),
        sa.Column("identity_fingerprint", sa.Text),
        sa.Column("identity_prompt_hash", sa.Text),
        sa.Column("identity_input_hash", sa.Text),
        sa.Column("identity_exchange_id", sa.Text),
    )
    op.create_index(
        "judge_invocation_policy_idx", "judge_invocation", ["policy_id"]
    )
    op.create_table(
        "judge_invocation_unsupported",
        _event_id("judge_invocation"),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("verdict", sa.Text, nullable=False),
    )
    op.create_table(
        "model_call",
        _event_id("review_journal"),
        sa.Column("call_id", sa.Text, nullable=False),
        sa.Column("archive_folder", sa.Text),
        sa.Column("purpose", sa.Text, nullable=False),
        sa.Column("policy_id", sa.Text),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("http_status", sa.Integer),
        sa.Column("error", sa.Text),
        sa.Column("requested_model", sa.Text, nullable=False),
        sa.Column("answered_model", sa.Text),
        sa.Column("model_id", sa.Text),
        sa.Column("model_group", sa.Text),
        sa.Column("api_base", sa.Text),
        sa.Column("proxy_version", sa.Text),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("retries", sa.Integer),
        sa.Column("fallbacks", sa.Integer),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("cached_input_tokens", sa.Integer),
        sa.Column("cache_creation_input_tokens", sa.Integer),
        sa.Column("reasoning_output_tokens", sa.Integer),
        sa.Column("total_tokens", sa.Integer),
        sa.Column("cost_usd", sa.Numeric),
        sa.Column("cost_nanodollars", sa.BigInteger),
        sa.Column("cost_input_usd", sa.Numeric),
        sa.Column("cost_output_usd", sa.Numeric),
        sa.Column("cost_cache_read_usd", sa.Numeric),
        sa.Column("cost_cache_creation_usd", sa.Numeric),
        sa.Column("cost_reasoning_usd", sa.Numeric),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("client_duration_ms", sa.Float, nullable=False),
        sa.Column("provider_duration_ms", sa.Float),
        sa.Column("proxy_overhead_ms", sa.Float),
        sa.Column("trace_id", sa.Text),
        sa.Column("span_id", sa.Text),
    )
    op.create_index("model_call_call_id_idx", "model_call", ["call_id"])
    op.create_index("model_call_policy_idx", "model_call", ["policy_id"])
    op.create_table(
        "model_call_finish_reason",
        _event_id("model_call"),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("reason", sa.Text, nullable=False),
    )
    op.create_table(
        "model_call_object",
        _event_id("model_call"),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("hop", sa.Text, nullable=False),
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("bytes", sa.BigInteger, nullable=False),
        sa.Column("encoding", sa.Text, nullable=False),
    )
    op.create_table(
        "policy_check",
        _event_id("review_journal"),
        sa.Column("policy_id", sa.Text, nullable=False),
        sa.Column("clause", sa.Text, nullable=False),
        sa.Column("finding_count", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Float),
    )
    op.create_table(
        "review_grade",
        _event_id("review_journal"),
        sa.Column("agent_id", sa.Text, nullable=False),
        sa.Column("detail", sa.Text, nullable=False),
        sa.Column("status", sa.Text),
    )
    op.create_table(
        "completion",
        _event_id("review_journal"),
        sa.Column("runner", sa.Text, nullable=False),
        sa.Column("remote_id", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
    )
    op.create_index(
        "completion_remote_idx", "completion", ["runner", "remote_id"]
    )

    op.execute(
        """
        INSERT INTO review_action (event_id, action, performed, status,
            agent_id, comment_id, verdict, head_sha, finding_count,
            raised_count, fixed_count, dismissed_count, context, state,
            description, label)
        SELECT event_id, payload->>'action', (payload->>'performed')::boolean,
               payload->>'status', payload->>'agent_id',
               (payload->>'comment_id')::bigint, payload->>'verdict',
               payload->>'head_sha', (payload->>'finding_count')::integer,
               (payload->>'raised_count')::integer,
               (payload->>'fixed_count')::integer,
               (payload->>'dismissed_count')::integer, payload->>'context',
               payload->>'state', payload->>'description', payload->>'label'
        FROM review_journal WHERE event_type = 'action.taken'
        """
    )
    op.execute(
        """
        INSERT INTO review_action_removed_label (event_id, label)
        SELECT DISTINCT j.event_id, l
        FROM review_journal j,
             jsonb_array_elements_text(j.payload->'removed') l
        WHERE j.event_type = 'action.taken'
        """
    )
    op.execute(
        """
        INSERT INTO agent_dispatch (event_id, agent_id, step, runner,
            fingerprint, remote_id, budget_usd, budget_turns, cost_usd,
            cost_seconds, events, detail, outcome, write_up_id,
            dispatched_at, reason, reviewed_in)
        SELECT event_id, payload->>'agent_id', payload->>'step',
               payload->>'runner', payload->>'fingerprint',
               payload->>'remote_id',
               (payload->'budget'->>'usd')::double precision,
               (payload->'budget'->>'turns')::double precision,
               (payload->'cost'->>'usd')::double precision,
               (payload->'cost'->>'seconds')::double precision,
               (payload->>'events')::integer, payload->>'detail',
               payload->>'outcome', payload->>'write_up_id',
               (payload->>'dispatched_at')::timestamptz, payload->>'reason',
               payload->>'reviewed_in'
        FROM review_journal WHERE event_type = 'agent.dispatched'
        """
    )
    op.execute(
        """
        INSERT INTO agent_dispatch_withheld_file (event_id, position, path)
        SELECT j.event_id, w.ordinality - 1, w.value
        FROM review_journal j,
             jsonb_array_elements_text(j.payload->'withheld') WITH ORDINALITY w
        WHERE j.event_type = 'agent.dispatched'
        """
    )
    op.execute(
        f"""
        INSERT INTO raised_finding (event_id, {FINDING_COLUMNS})
        SELECT event_id, {FINDING_SELECT}
        FROM review_journal WHERE event_type = 'finding.raised'
        """
    )
    for table, event_type in (
        ("resolved_finding", "finding.resolved"),
        ("rewritten_finding", "finding.rewritten"),
    ):
        op.execute(
            f"""
            INSERT INTO {table} (event_id, {FINDING_COLUMNS},
                raised_in_workflow_id, raised_in_run_id)
            SELECT event_id, {FINDING_SELECT},
                   payload->>'raised_in_workflow_id',
                   payload->>'raised_in_run_id'
            FROM review_journal WHERE event_type = '{event_type}'
            """
        )
    op.execute(
        f"""
        INSERT INTO withheld_finding (event_id, {FINDING_COLUMNS}, share)
        SELECT event_id, {FINDING_SELECT},
               (payload->>'share')::double precision
        FROM review_journal WHERE event_type = 'finding.withheld'
        """
    )
    op.execute(
        """
        INSERT INTO judge_invocation (event_id, policy_id, status, model,
            finding_count, input_tokens, output_tokens, identity_model,
            identity_fingerprint, identity_prompt_hash, identity_input_hash,
            identity_exchange_id)
        SELECT event_id, payload->>'policy_id', payload->>'status',
               payload->>'model', (payload->>'finding_count')::integer,
               (payload->>'input_tokens')::integer,
               (payload->>'output_tokens')::integer,
               payload->'identity'->>'model',
               payload->'identity'->>'fingerprint',
               payload->'identity'->>'prompt_hash',
               payload->'identity'->>'input_hash',
               payload->'identity'->>'exchange_id'
        FROM review_journal WHERE event_type = 'judge.invoked'
        """
    )
    op.execute(
        """
        INSERT INTO judge_invocation_unsupported (event_id, position, verdict)
        SELECT j.event_id, u.ordinality - 1, u.value
        FROM review_journal j,
             jsonb_array_elements_text(j.payload->'unsupported')
                 WITH ORDINALITY u
        WHERE j.event_type = 'judge.invoked'
        """
    )
    op.execute(
        """
        INSERT INTO model_call (event_id, call_id, archive_folder, purpose,
            policy_id, status, http_status, error, requested_model,
            answered_model, model_id, model_group, api_base, proxy_version,
            attempt, retries, fallbacks, input_tokens, output_tokens,
            cached_input_tokens, cache_creation_input_tokens,
            reasoning_output_tokens, total_tokens, cost_usd,
            cost_nanodollars, cost_input_usd, cost_output_usd,
            cost_cache_read_usd, cost_cache_creation_usd, cost_reasoning_usd,
            started_at, ended_at, client_duration_ms, provider_duration_ms,
            proxy_overhead_ms, trace_id, span_id)
        SELECT event_id, payload->>'call_id', payload->>'archive_folder',
               payload->>'purpose', payload->>'policy_id', payload->>'status',
               (payload->>'http_status')::integer, payload->>'error',
               payload->>'requested_model', payload->>'answered_model',
               payload->>'model_id', payload->>'model_group',
               payload->>'api_base', payload->>'proxy_version',
               (payload->>'attempt')::integer, (payload->>'retries')::integer,
               (payload->>'fallbacks')::integer,
               (payload->>'input_tokens')::integer,
               (payload->>'output_tokens')::integer,
               (payload->>'cached_input_tokens')::integer,
               (payload->>'cache_creation_input_tokens')::integer,
               (payload->>'reasoning_output_tokens')::integer,
               (payload->>'total_tokens')::integer,
               (payload->>'cost_usd')::numeric,
               (payload->>'cost_nanodollars')::bigint,
               (payload->>'cost_input_usd')::numeric,
               (payload->>'cost_output_usd')::numeric,
               (payload->>'cost_cache_read_usd')::numeric,
               (payload->>'cost_cache_creation_usd')::numeric,
               (payload->>'cost_reasoning_usd')::numeric,
               (payload->>'started_at')::timestamptz,
               (payload->>'ended_at')::timestamptz,
               (payload->>'client_duration_ms')::double precision,
               (payload->>'provider_duration_ms')::double precision,
               (payload->>'proxy_overhead_ms')::double precision,
               payload->>'trace_id', payload->>'span_id'
        FROM review_journal WHERE event_type = 'llm.called'
        """
    )
    op.execute(
        """
        INSERT INTO model_call_finish_reason (event_id, position, reason)
        SELECT j.event_id, r.ordinality - 1, r.value
        FROM review_journal j,
             jsonb_array_elements_text(j.payload->'finish_reasons')
                 WITH ORDINALITY r
        WHERE j.event_type = 'llm.called'
        """
    )
    op.execute(
        """
        INSERT INTO model_call_object (event_id, position, hop, key, sha256,
                                       bytes, encoding)
        SELECT j.event_id, o.ordinality - 1, o.value->>'hop', o.value->>'key',
               o.value->>'sha256', (o.value->>'bytes')::bigint,
               o.value->>'encoding'
        FROM review_journal j,
             jsonb_array_elements(j.payload->'objects') WITH ORDINALITY o
        WHERE j.event_type = 'llm.called'
        """
    )
    op.execute(
        """
        INSERT INTO policy_check (event_id, policy_id, clause, finding_count,
                                  cost_usd)
        SELECT event_id, payload->>'policy_id', payload->>'clause',
               (payload->>'finding_count')::integer,
               (payload->'cost'->>'usd')::double precision
        FROM review_journal WHERE event_type = 'policy.checked'
        """
    )
    op.execute(
        """
        INSERT INTO review_grade (event_id, agent_id, detail, status)
        SELECT event_id, payload->>'agent_id', payload->>'detail',
               payload->>'status'
        FROM review_journal WHERE event_type = 'review.graded'
        """
    )
    op.execute(
        """
        INSERT INTO completion (event_id, runner, remote_id, outcome, reason)
        SELECT event_id, payload->>'runner', payload->>'remote_id',
               payload->>'outcome', payload->>'reason'
        FROM review_journal WHERE event_type = 'completion.received'
        """
    )


def downgrade() -> None:
    for table in (
        "completion",
        "review_grade",
        "policy_check",
        "model_call_object",
        "model_call_finish_reason",
        "model_call",
        "judge_invocation_unsupported",
        "judge_invocation",
        "withheld_finding",
        "rewritten_finding",
        "resolved_finding",
        "raised_finding",
        "agent_dispatch_withheld_file",
        "agent_dispatch",
        "review_action_removed_label",
        "review_action",
    ):
        op.drop_table(table)
