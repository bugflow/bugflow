"""The disposition of a finding: what a person decided to do about it.

Some findings cannot be settled by software, and a person decides. The
decision is recorded as one of five dispositions, so that a count of
open findings can tell a finding that is finished from one that still
has work to do:

- "accepted_done": the finding was accepted and the change has been
  made.
- "accepted_follow_up_pending": the finding was accepted, and the work
  it calls for has not been done yet.
- "deferred": the finding is real, and is put off until later.
- "rejected": the finding was considered and nothing will be done.
- "routed_to_question": the finding was not decided. A question was
  put to somebody instead, and the record gives the question's id.

Only "accepted_done" and "rejected" close a finding by themselves. A
finding with "routed_to_question" closes when its question has been
answered. The others stay open.
"""

from typing import Literal

Disposition = Literal[
    "accepted_done",
    "accepted_follow_up_pending",
    "deferred",
    "rejected",
    "routed_to_question",
]

#: Every disposition, for checking that a value read from a file is one.
DISPOSITIONS: tuple[Disposition, ...] = (
    "accepted_done",
    "accepted_follow_up_pending",
    "deferred",
    "rejected",
    "routed_to_question",
)

ROUTED_TO_QUESTION: Disposition = "routed_to_question"

#: The dispositions that close a finding by themselves.
TERMINAL_DISPOSITIONS: tuple[Disposition, ...] = ("accepted_done", "rejected")

#: The disposition a record is read as when it gives none. Records made
#: before dispositions existed marked a finding as settled, with no
#: conditions.
DEFAULT_DISPOSITION: Disposition = "accepted_done"


def is_terminal(disposition: Disposition) -> bool:
    """Whether the disposition closes a finding by itself."""
    return disposition in TERMINAL_DISPOSITIONS


def closes_finding(
    disposition: Disposition,
    question_id: str | None,
    resolved_question_ids: frozenset[str],
) -> bool:
    """Whether a recorded decision closes its finding.

    ``question_id`` is the question the finding was routed to, if it
    was. ``resolved_question_ids`` are the questions that have been
    answered; the caller reads them from wherever questions are kept.

    Every place that asks whether a finding is closed uses this
    function, so that they cannot disagree.
    """
    if is_terminal(disposition):
        return True
    if disposition == ROUTED_TO_QUESTION:
        return question_id is not None and question_id in resolved_question_ids
    return False
