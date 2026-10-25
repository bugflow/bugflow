"""The payloads of the forge's facts as a test writes them whole, so that
the fact's unpacker fills its table (ADR 007). A test that writes a forge
fact through the unpackers gives it one of these."""

from typing import Any


def observed(snapshot_id: str) -> dict[str, Any]:
    """An observation of a pull request that read ``snapshot_id``."""
    return {
        "snapshot_id": snapshot_id,
        "delivery_id": None,
        "delivery_ids": [],
        "corpus": {},
        "title": "A change",
        "head_branch": "change",
        "base_branch": "main",
        "author_login": "author",
        "commits": [],
        "file_count": 1,
        "changed_lines": 2,
    }


def received(delivery_id: str) -> dict[str, Any]:
    """A delivery the forge sent, which the ingress did nothing with."""
    return {
        "delivery_id": delivery_id,
        "event": "pull_request",
        "action": "labeled",
        "outcome": "ignored",
        "reason": "",
    }


def dismissed(policy_id: str, reason: str) -> dict[str, Any]:
    """A person's dismissal of a policy on a pull request."""
    return {
        "policy_id": policy_id,
        "reason": reason,
        "actor": "reviewer",
        "comment_id": 99,
        "delivery_id": "d-1",
    }
