"""A dismissal: a person saying they disagree with a policy's findings on
a pull request.

A person dismisses by writing a comment on the pull request whose first
line is ``/dismiss <policy-id> <reason>``, for example
``/dismiss ED-01 this sentence is a quotation``. The reason is required.
A dismissal is evidence about how well the policy works, and one with no
reason tells nobody anything.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self

_COMMAND = re.compile(r"^/dismiss\s+([A-Z]+-\d+)\s+(\S.*)$")


@dataclass(frozen=True, kw_only=True)
class Dismissal:
    policy_id: str
    reason: str
    #: Who dismissed, by their name on the forge. None if not known.
    actor: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> Self:
        """Rebuild a dismissal from the payload of the journal entry that
        recorded it."""
        return cls(
            policy_id=payload["policy_id"],
            reason=payload["reason"],
            actor=payload.get("actor"),
        )


def parse_dismissal(text: str) -> Dismissal | None:
    """Read a dismissal from a comment's text. Returns None if the
    comment's first line is not a ``/dismiss`` command with a policy id
    and a reason."""
    lines = text.strip().splitlines()
    match = _COMMAND.match(lines[0].strip()) if lines else None
    if match is None:
        return None
    return Dismissal(policy_id=match.group(1), reason=match.group(2).strip())
