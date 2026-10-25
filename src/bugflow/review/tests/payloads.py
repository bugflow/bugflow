"""The payloads of the review's facts as a test writes them whole, so
that the fact's unpacker fills its table and the in-memory journal reads
the fact as the table holds it (ADR 007). ``whole`` completes a partial
payload of any review or stocktake type; a type with no table is
returned as given."""

from collections.abc import Mapping
from typing import Any


def _identity(**fields: Any) -> dict[str, Any]:
    """A judge identity, with the five keys its table takes."""
    return {
        "model": "a-model",
        "fingerprint": "fp",
        "prompt_hash": None,
        "input_hash": "ih",
        "exchange_id": None,
    } | fields


def _finding(**fields: Any) -> dict[str, Any]:
    judge = fields.pop("judge", None)
    return {
        "policy_id": "P-01",
        "severity": "warn",
        "clause": "RULE-1",
        "subject": "pull request",
        "message": "a message",
        "judged_by": None,
        "judge": _identity(**judge) if judge else None,
        "corpus_version": None,
    } | fields


def _raised_in(**fields: Any) -> dict[str, Any]:
    return {
        "raised_in_workflow_id": "pr-1",
        "raised_in_run_id": "r0",
    } | fields


#: The keys each step of a dispatch carries, beside the agent and the
#: step, with the values a test leaves alone.
_STEPS: dict[str, dict[str, Any]] = {
    "dispatched": {
        "runner": "hosted",
        "fingerprint": "f1",
        "remote_id": "s-1",
        "budget": None,
        "withheld": [],
    },
    "collected": {
        "outcome": "completed",
        "runner": "hosted",
        "fingerprint": "f1",
        "cost": None,
        "events": 0,
        "detail": "",
    },
    "recovered": {
        "runner": "hosted",
        "remote_id": "s-1",
        "write_up_id": "w-1",
        "outcome": "completed",
        "dispatched_at": None,
    },
    "refused": {"reason": "refused"},
    "reused": {"fingerprint": "f1", "reviewed_in": "r0"},
    "no-worktree": {"reason": "no worktree"},
    "unavailable": {"reason": "unavailable"},
}

#: The keys each kind of action carries, beside the action, whether it
#: was performed and its status.
_ACTIONS: dict[str, dict[str, Any]] = {
    "review_comment": {
        "agent_id": None,
        "comment_id": None,
        "verdict": None,
        "head_sha": None,
        "finding_count": 0,
        "raised_count": 0,
        "fixed_count": 0,
        "dismissed_count": 0,
    },
    "commit_status": {
        "context": "bugflow",
        "state": "success",
        "description": "",
    },
    "outcome_label": {"label": "", "removed": []},
    "summary_comment": {
        "comment_id": None,
        "finding_count": 0,
        "raised_count": 0,
        "fixed_count": 0,
        "dismissed_count": 0,
    },
}


def raised(**fields: Any) -> dict[str, Any]:
    """A raised finding."""
    return _finding(**fields)


def resolved(**fields: Any) -> dict[str, Any]:
    """A finding an earlier evaluation raised and this one did not."""
    raised_in = {
        k: fields.pop(k) for k in list(fields) if k.startswith("raised_in")
    }
    return _finding(**fields) | _raised_in(**raised_in)


def rewritten(**fields: Any) -> dict[str, Any]:
    """A finding whose quoted words are gone."""
    return resolved(**fields)


def withheld(**fields: Any) -> dict[str, Any]:
    """A warning kept out of the pull request."""
    share = fields.pop("share", 0.5)
    return _finding(**fields) | {"share": share}


def judged(**fields: Any) -> dict[str, Any]:
    """A judge was asked about one policy."""
    identity = fields.pop("identity", None)
    return {
        "policy_id": "P-01",
        "status": "judged by a-model",
        "model": "a-model",
        "finding_count": 0,
        "unsupported": [],
        "input_tokens": 0,
        "output_tokens": 0,
        "identity": _identity(**identity) if identity else None,
    } | fields


def called(**fields: Any) -> dict[str, Any]:
    """One call to a language model."""
    return {
        "call_id": "call-1",
        "archive_folder": None,
        "purpose": "judge",
        "policy_id": None,
        "status": "answered",
        "http_status": 200,
        "error": None,
        "requested_model": "a-model",
        "answered_model": "a-model",
        "model_id": None,
        "model_group": None,
        "api_base": None,
        "proxy_version": None,
        "attempt": 1,
        "retries": 0,
        "fallbacks": 0,
        "finish_reasons": ["stop"],
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": None,
        "cost_nanodollars": None,
        "cost_input_usd": None,
        "cost_output_usd": None,
        "cost_cache_read_usd": None,
        "cost_cache_creation_usd": None,
        "cost_reasoning_usd": None,
        "started_at": "2030-01-01T00:00:00+00:00",
        "ended_at": "2030-01-01T00:00:01+00:00",
        "client_duration_ms": 1000.0,
        "provider_duration_ms": None,
        "proxy_overhead_ms": None,
        "trace_id": None,
        "span_id": None,
        "objects": [],
    } | fields


def checked(**fields: Any) -> dict[str, Any]:
    """A checked policy's run."""
    return {
        "policy_id": "P-01",
        "clause": "RULE-1",
        "finding_count": 0,
    } | fields


def graded(**fields: Any) -> dict[str, Any]:
    """A grader's verdict on a write-up."""
    return {"agent_id": "security", "status": "pass", "detail": ""} | fields


def dispatched(**fields: Any) -> dict[str, Any]:
    """A step of a checkout agent's dispatch, ``dispatched`` unless the
    fields say which."""
    step = fields.get("step", "dispatched")
    return {"agent_id": "security", "step": step} | _STEPS[step] | fields


def acted(**fields: Any) -> dict[str, Any]:
    """An action on the pull request, a review comment unless the fields
    say which."""
    action = fields.get("action", "review_comment")
    return (
        {"action": action, "performed": True, "status": "posted"}
        | _ACTIONS[action]
        | fields
    )


def taken_stock(**fields: Any) -> dict[str, Any]:
    """A stocktake's review of its range."""
    return {
        "layer": "weekly",
        "agent_id": "security",
        "outcome": "completed",
        "cost": None,
        "detail": "",
        "write_up": "",
    } | fields


_WHOLE = {
    "finding.raised": raised,
    "finding.resolved": resolved,
    "finding.rewritten": rewritten,
    "finding.withheld": withheld,
    "judge.invoked": judged,
    "llm.called": called,
    "policy.checked": checked,
    "review.graded": graded,
    "agent.dispatched": dispatched,
    "action.taken": acted,
    "stocktake.reviewed": taken_stock,
}


def whole(event_type: str, **fields: Any) -> dict[str, Any]:
    """The payload of a fact of this type with ``fields``, the rest of
    what its table takes filled in; for a type with no table here, the
    fields alone."""
    make = _WHOLE.get(event_type)
    return make(**fields) if make else dict(fields)


def completed(event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """``payload`` made whole for its type."""
    return whole(event_type, **payload)
