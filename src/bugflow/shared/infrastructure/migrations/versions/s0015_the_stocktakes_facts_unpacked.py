"""Unpack the stocktake's facts into tables named for what one row is
(ADR 007), the fourth journal to be unpacked.

Creates stocktake and stocktake_pull_request for stocktake.taken;
stocktake_dispatch for stocktake.dispatched; stocktake_review for
stocktake.reviewed; stocktake_finding for stocktake.found; and
stocktake_grade for stocktake.graded. Each is keyed by the event's id to
the stocktake journal, and the script fills them from every row there.

A dispatch's keys depend on its step, so the check reads each row
against the keys its step had at the inventory of 25 October 2026, and
the keys the code writes for the two steps that record no run, and
stops on a step outside those. It stops too on a key outside the
inventory at the top level or inside a cost, on a pull request that is
not a number and on a time that is not ISO 8601. No fact is unpacked by
guess. The payload column stays until the journal's last type is
unpacked.

The downgrade drops the six tables.
"""

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0015"
down_revision = "0014"

#: What each fact's payload holds: the keys every row has, and the keys
#: some rows have. A key outside both stops the script.
REQUIRED: dict[str, tuple[str, ...]] = {
    "stocktake.taken": (
        "layer",
        "since",
        "until",
        "merged",
        "pull_requests",
        "base_sha",
        "head_sha",
    ),
    "stocktake.reviewed": (
        "layer",
        "agent_id",
        "outcome",
        "cost",
        "detail",
        "write_up",
    ),
    "stocktake.found": (
        "layer",
        "agent_id",
        "index",
        "where",
        "quote",
        "claim",
        "kind",
    ),
    "stocktake.graded": ("layer", "agent_id", "status", "detail"),
}
OPTIONAL: dict[str, tuple[str, ...]] = {
    "stocktake.taken": (),
    "stocktake.reviewed": (),
    "stocktake.found": (),
    "stocktake.graded": (),
}

#: The keys each step of a dispatch carries, by its ``step``: the step
#: the inventory found, and the two the code writes for a run that did
#: not start.
STEP_KEYS: dict[str, tuple[str, ...]] = {
    "dispatched": (
        "layer",
        "agent_id",
        "base_sha",
        "head_sha",
        "step",
        "remote_id",
    ),
    "refused": ("layer", "agent_id", "base_sha", "head_sha", "step", "reason"),
    "unavailable": (
        "layer",
        "agent_id",
        "base_sha",
        "head_sha",
        "step",
        "reason",
    ),
}
#: The first dispatch, on 24 September 2026, recorded no runner.
STEP_OPTIONAL: dict[str, tuple[str, ...]] = {"dispatched": ("runner",)}

#: The keys an object inside a payload has, where the object is there.
OBJECT_KEYS = {("stocktake.reviewed", "cost"): ("usd", "seconds")}

#: The lists whose every element is a number.
NUMBER_LISTS = (("stocktake.taken", "pull_requests"),)

#: The strings that are times, where they are strings.
TIMES = (("stocktake.taken", "since"), ("stocktake.taken", "until"))

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
            "SELECT count(*) FROM stocktake_journal WHERE event_type = :t "
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
                "SELECT count(*) FROM stocktake_journal WHERE event_type = :t "
                f"{where} AND NOT payload ? :k",
                t=event_type,
                k=key,
                **params,
            ),
            event_type,
            f"lack {key!r}, which every such row had at the inventory",
        )


def _check_shapes() -> None:
    for event_type in ("stocktake.dispatched", *REQUIRED):
        _stop(
            _count(
                "SELECT count(*) FROM stocktake_journal WHERE event_type = :t "
                "AND jsonb_typeof(payload) <> 'object'",
                t=event_type,
            ),
            event_type,
            "carry a payload that is not an object",
        )
    for event_type, required in REQUIRED.items():
        _check_keys(event_type, required, OPTIONAL[event_type])
    _stop(
        _count(
            "SELECT count(*) FROM stocktake_journal WHERE event_type = :t "
            "AND NOT payload->>'step' = ANY(CAST(:kinds AS text[]))",
            t="stocktake.dispatched",
            kinds=sorted(STEP_KEYS),
        ),
        "stocktake.dispatched",
        "carry a kind of step the inventory did not find",
    )
    for value, required in STEP_KEYS.items():
        _check_keys(
            "stocktake.dispatched",
            required,
            STEP_OPTIONAL.get(value, ()),
            where="AND payload->>'step' = :v",
            v=value,
        )
    for (event_type, key), object_keys in OBJECT_KEYS.items():
        _stop(
            _count(
                "SELECT count(*) FROM stocktake_journal WHERE event_type = :t "
                f"AND payload ? '{key}' AND jsonb_typeof(payload->'{key}') "
                "NOT IN ('object', 'null')",
                t=event_type,
            ),
            event_type,
            f"carry a {key} that is not an object",
        )
        _stop(
            _count(
                "SELECT count(*) FROM stocktake_journal WHERE event_type = :t "
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
    for event_type, key in NUMBER_LISTS:
        _stop(
            _count(
                "SELECT count(DISTINCT j.event_id) FROM stocktake_journal j, "
                f"jsonb_array_elements(j.payload->'{key}') e "
                "WHERE j.event_type = :t AND jsonb_typeof(e) <> 'number'",
                t=event_type,
            ),
            event_type,
            f"carry a {key} element that is not a number",
        )
    for event_type, key in TIMES:
        _stop(
            _count(
                "SELECT count(*) FROM stocktake_journal WHERE event_type = :t "
                f"AND jsonb_typeof(payload->'{key}') = 'string' "
                f"AND NOT (payload->>'{key}') ~ :pattern",
                t=event_type,
                pattern=ISO,
            ),
            event_type,
            f"carry a {key} that is not a time",
        )


def upgrade() -> None:
    _check_shapes()

    op.create_table(
        "stocktake",
        _event_id("stocktake_journal"),
        sa.Column("layer", sa.Text, nullable=False),
        sa.Column("since", sa.DateTime(timezone=True)),
        sa.Column("until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("merged", sa.Integer, nullable=False),
        sa.Column("base_sha", sa.Text),
        sa.Column("head_sha", sa.Text),
    )
    op.create_index("stocktake_layer_idx", "stocktake", ["layer"])
    op.create_table(
        "stocktake_pull_request",
        _event_id("stocktake"),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("pull_request", sa.Integer, nullable=False),
    )
    op.create_table(
        "stocktake_dispatch",
        _event_id("stocktake_journal"),
        sa.Column("layer", sa.Text, nullable=False),
        sa.Column("agent_id", sa.Text, nullable=False),
        sa.Column("base_sha", sa.Text),
        sa.Column("head_sha", sa.Text),
        sa.Column("step", sa.Text, nullable=False),
        sa.Column("runner", sa.Text),
        sa.Column("remote_id", sa.Text),
        sa.Column("reason", sa.Text),
    )
    op.create_index(
        "stocktake_dispatch_step_idx", "stocktake_dispatch", ["step"]
    )
    op.create_index(
        "stocktake_dispatch_remote_idx",
        "stocktake_dispatch",
        ["runner", "remote_id"],
    )
    op.create_table(
        "stocktake_review",
        _event_id("stocktake_journal"),
        sa.Column("layer", sa.Text, nullable=False),
        sa.Column("agent_id", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("cost_usd", sa.Float),
        sa.Column("cost_seconds", sa.Float),
        sa.Column("detail", sa.Text, nullable=False),
        sa.Column("write_up", sa.Text, nullable=False),
    )
    op.create_table(
        "stocktake_finding",
        _event_id("stocktake_journal"),
        sa.Column("layer", sa.Text, nullable=False),
        sa.Column("agent_id", sa.Text, nullable=False),
        sa.Column("index", sa.Integer, nullable=False),
        sa.Column("location", sa.Text, nullable=False),
        sa.Column("quote", sa.Text, nullable=False),
        sa.Column("claim", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
    )
    op.create_table(
        "stocktake_grade",
        _event_id("stocktake_journal"),
        sa.Column("layer", sa.Text, nullable=False),
        sa.Column("agent_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text),
        sa.Column("detail", sa.Text, nullable=False),
    )

    op.execute(
        """
        INSERT INTO stocktake (event_id, layer, since, until, merged,
                               base_sha, head_sha)
        SELECT event_id, payload->>'layer',
               (payload->>'since')::timestamptz,
               (payload->>'until')::timestamptz,
               (payload->>'merged')::integer, payload->>'base_sha',
               payload->>'head_sha'
        FROM stocktake_journal WHERE event_type = 'stocktake.taken'
        """
    )
    op.execute(
        """
        INSERT INTO stocktake_pull_request (event_id, position, pull_request)
        SELECT j.event_id, p.ordinality - 1, p.value::integer
        FROM stocktake_journal j,
             jsonb_array_elements_text(j.payload->'pull_requests')
                 WITH ORDINALITY p
        WHERE j.event_type = 'stocktake.taken'
        """
    )
    op.execute(
        """
        INSERT INTO stocktake_dispatch (event_id, layer, agent_id, base_sha,
            head_sha, step, runner, remote_id, reason)
        SELECT event_id, payload->>'layer', payload->>'agent_id',
               payload->>'base_sha', payload->>'head_sha', payload->>'step',
               payload->>'runner', payload->>'remote_id', payload->>'reason'
        FROM stocktake_journal WHERE event_type = 'stocktake.dispatched'
        """
    )
    op.execute(
        """
        INSERT INTO stocktake_review (event_id, layer, agent_id, outcome,
            cost_usd, cost_seconds, detail, write_up)
        SELECT event_id, payload->>'layer', payload->>'agent_id',
               payload->>'outcome',
               (payload->'cost'->>'usd')::double precision,
               (payload->'cost'->>'seconds')::double precision,
               payload->>'detail', payload->>'write_up'
        FROM stocktake_journal WHERE event_type = 'stocktake.reviewed'
        """
    )
    op.execute(
        """
        INSERT INTO stocktake_finding (event_id, layer, agent_id, index,
            location, quote, claim, kind)
        SELECT event_id, payload->>'layer', payload->>'agent_id',
               (payload->>'index')::integer, payload->>'where',
               payload->>'quote', payload->>'claim', payload->>'kind'
        FROM stocktake_journal WHERE event_type = 'stocktake.found'
        """
    )
    op.execute(
        """
        INSERT INTO stocktake_grade (event_id, layer, agent_id, status, detail)
        SELECT event_id, payload->>'layer', payload->>'agent_id',
               payload->>'status', payload->>'detail'
        FROM stocktake_journal WHERE event_type = 'stocktake.graded'
        """
    )


def downgrade() -> None:
    for table in (
        "stocktake_pull_request",
        "stocktake",
        "stocktake_dispatch",
        "stocktake_review",
        "stocktake_finding",
        "stocktake_grade",
    ):
        op.drop_table(table)
