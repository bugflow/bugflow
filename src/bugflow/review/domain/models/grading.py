"""A write-up as the grader is given it, and what the grader says about
it."""

import re
from dataclasses import dataclass, field
from typing import Literal

from bugflow.shared.domain.models.call_record import CallRecord

#: How the run that produced a write-up ended. The words are the work
#: context's.
WriteupOutcome = Literal[
    "running",
    "completed",
    "stopped_short",
    "declined",
    "failed",
    "malformed",
]

#: The outcomes whose write-up is graded. A "malformed" run did answer,
#: only not in the shape its task asked for. The grader reads the prose
#: and nothing else, so that write-up is graded like any other.
ANSWERED: tuple[WriteupOutcome, ...] = ("completed", "malformed")


@dataclass(frozen=True, kw_only=True)
class Writeup:
    """One reviewer's write-up about one commit, with how its run ended
    and what it cost."""

    agent_id: str
    head_sha: str
    write_up: str
    outcome: WriteupOutcome
    cost: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class Grading:
    """What the grader said about a write-up."""

    #: The verdict the write-up supports. None if the write-up does not
    #: answer what was asked; the pull request's label then stays
    #: "review:wip" for this reviewer.
    status: Literal["pass", "warn", "fail"] | None = None
    #: The grader's reason.
    detail: str = ""
    #: Whether the write-up's note to the author is fit to show the
    #: author. The verdict stands either way.
    note_fit: bool = False
    #: The calls the grader made to a model, so that they can be
    #: recorded and their cost counted.
    calls: tuple[CallRecord, ...] = ()


# The heading that starts a write-up's note to the author. Everything
# after it is the note.
_NOTE_HEADING = re.compile(
    r"^#{1,6}[ \t]*For the author[ \t]*:?[ \t]*$", re.IGNORECASE | re.MULTILINE
)


def author_note(write_up: str) -> str:
    """The part of a write-up addressed to the pull request's author:
    everything after a heading "For the author".

    Empty if the write-up has no such heading. The rest of a write-up
    is the reviewer's own working and is not shown to the author.
    """
    heading = _NOTE_HEADING.search(write_up)
    if heading is None:
        return ""
    return write_up[heading.end() :].strip()
