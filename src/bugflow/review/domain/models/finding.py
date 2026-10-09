"""A finding: one policy's verdict about one thing in a pull request."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from bugflow.review.domain.models.judgement import JudgeIdentity

Severity = Literal["info", "warn", "fail"]


@dataclass(frozen=True, kw_only=True)
class Finding:
    policy_id: str
    severity: Severity
    #: The id of the doctrine clause the finding rests on. Every finding
    #: has one.
    clause: str
    #: What the finding is about: a commit's short id, or "pull
    #: request".
    subject: str
    message: str
    #: The model that produced the finding. None for a finding from a
    #: checked policy.
    judged_by: str | None = None
    #: What identifies the judgement the finding came from. None for a
    #: finding from a checked policy.
    judge: JudgeIdentity | None = None
    #: The version of the corpus the finding was raised under. If a
    #: reviewer raised it, this is that reviewer's own version.
    corpus_version: str | None = None
    #: The reviewer whose policy this is. None on a server with no
    #: reviewer installed.
    agent_id: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> Self:
        """Build a finding from the payload of the journal entry that
        recorded it."""
        judge = payload.get("judge")
        return cls(
            policy_id=payload["policy_id"],
            severity=payload["severity"],
            clause=payload["clause"],
            subject=payload["subject"],
            message=payload["message"],
            judged_by=payload.get("judged_by"),
            judge=JudgeIdentity(**judge) if judge else None,
            corpus_version=payload.get("corpus_version"),
            agent_id=payload.get("agent_id"),
        )
