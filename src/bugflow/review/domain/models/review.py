"""A reviewer's verdict on a commit, and the label that the verdicts of
all the reviewers give a pull request.

A verdict is about one reviewer and one commit. When a new commit is
pushed, the verdicts about the earlier commit no longer count, and
nothing has to mark them as out of date.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

#: A reviewer's result for a commit. "warn" means there is something for
#: the author to look at. It does not block anything.
ReviewStatus = Literal["pass", "warn", "fail"]

#: The label put on a pull request. There is one, however many reviewers
#: there are.
#:
#: - "review:wip": not every reviewer has given a verdict yet.
#: - "review:pass": every reviewer has, and none failed.
#: - "review:escalate": a reviewer failed the commit, and a person
#:   should look.
LabelState = Literal["review:wip", "review:pass", "review:escalate"]


@dataclass(frozen=True, kw_only=True)
class ReviewVerdict:
    """One reviewer's verdict on one commit."""

    agent_id: str
    #: The commit that was reviewed.
    head_sha: str
    status: ReviewStatus


@dataclass(frozen=True, kw_only=True)
class ReviewNote:
    """What a checkout agent has to say to the author about one commit.
    It goes in the comment on the pull request."""

    agent_id: str
    head_sha: str
    #: The part of the write-up addressed to the author, if the grader
    #: found it fit to show. Empty otherwise.
    note: str = ""
    #: The whole write-up, given only when there is no note to show. The
    #: comment then carries it folded away.
    write_up: str = ""


def project(
    head_sha: str,
    governing: Iterable[str],
    verdicts: Iterable[ReviewVerdict],
) -> LabelState:
    """Work out the label for a pull request whose last commit is
    ``head_sha``.

    ``governing`` are the agent ids of the reviewers whose verdicts
    count for this repository. Verdicts from other reviewers and
    verdicts about other commits are ignored.

    The rules, in order:

    - If no reviewer governs the repository, the label is "review:wip".
      A repository with every reviewer switched off has not passed.
    - If any governing reviewer failed the commit, it is
      "review:escalate", even if others have not answered yet.
    - If any governing reviewer has given no verdict, it is
      "review:wip".
    - Otherwise it is "review:pass".
    """
    governing = frozenset(governing)
    if not governing:
        return "review:wip"
    current = {
        verdict.agent_id: verdict.status
        for verdict in verdicts
        if verdict.head_sha == head_sha and verdict.agent_id in governing
    }
    if "fail" in current.values():
        return "review:escalate"
    if governing - set(current):
        return "review:wip"
    return "review:pass"
