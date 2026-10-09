"""Choose which findings a comment on a pull request should carry.

Reviewers record findings. A comment is written afterwards, from every
finding recorded for the pull request across all its evaluations.

A judge asked twice about the same text does not always raise the same
findings. So a finding is put in the comment only if every evaluation of
the current text raised it. With one evaluation, that is every finding
it raised.

The cost of this rule: a finding that the second evaluation of a text
raised and the first did not is left out, although it may be right.

"The text" is what an evaluation read: the commits, the title and the
description. If the description is edited without a new commit, that is
a new text, and evaluations of the old one are not counted against it.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from bugflow.review.domain.models.finding import Finding

#: The order findings are shown in: the most severe first.
WEIGHT = {"fail": 0, "warn": 1, "info": 2}


@dataclass(frozen=True, kw_only=True)
class Seen:
    """One finding as one evaluation recorded it."""

    #: The evaluation's run id.
    run_id: str
    #: What identifies the text the evaluation read: the id of its
    #: stored submission, or its last commit if no submission was
    #: recorded.
    read: str
    finding: Finding


def _identity(finding: Finding) -> tuple[str, str, str]:
    # The message is left out. It may quote a count that changes while
    # the problem stays the same.
    return (finding.policy_id, finding.clause, finding.subject)


def worth_saying(history: Iterable[Seen], *, read: str) -> tuple[Finding, ...]:
    """The findings a comment about the text ``read`` should carry, the
    most severe first.

    ``history`` is every finding recorded for the pull request. Those
    from evaluations of another text are ignored. Of the rest, a finding
    is returned if every evaluation of this text raised it.
    """
    at_head = [seen for seen in history if seen.read == read]
    if not at_head:
        return ()
    runs = {seen.run_id for seen in at_head}
    raised_in: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    latest: dict[tuple[str, str, str], Finding] = {}
    for seen in at_head:
        raised_in[_identity(seen.finding)].add(seen.run_id)
        latest[_identity(seen.finding)] = seen.finding
    said = [
        finding
        for identity, finding in latest.items()
        if raised_in[identity] == runs
    ]
    return tuple(
        sorted(
            said,
            key=lambda f: (
                WEIGHT.get(f.severity, len(WEIGHT)),
                f.policy_id,
                f.clause,
                f.subject,
            ),
        )
    )
