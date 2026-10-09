"""The words a finding quotes, and whether a pull request still contains
them.

A judged finding is about words the author wrote. Its message starts
with those words in double quotes, followed by ``": `` and the
explanation. Whether the words are still in the pull request is decided
by comparing text. No model is asked.
"""

import re

from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.submission import Submission

#: The Markdown characters for code and emphasis. A model leaves them
#: out when it quotes.
MARKUP = re.compile(r"[`*_]")
_SEPARATOR = '": '
#: How many characters of a quotation a judge writes into a finding's
#: subject.
SUBJECT_QUOTE = 60


def normalised(text: str) -> str:
    """The text with each run of white space made one space."""
    return " ".join(text.split())


def unmarked(text: str) -> str:
    """The text as a model would quote it: Markdown characters removed
    and white space made single spaces."""
    return normalised(MARKUP.sub("", text))


def quoted(finding: Finding) -> str:
    """The words the finding quotes. Empty for a finding that quotes
    nothing.

    The quotation may itself contain ``": ``, so the message could be
    cut in more than one place. The finding's subject settles it: the
    judge writes the start of the quotation into the subject, and the
    longest cut that the subject agrees with is taken.
    """
    message = finding.message
    if not message.startswith('"'):
        return ""
    cuts = [message[1:at] for at in _separators(message) if message[1:at]]
    if not cuts:
        return ""
    agreed = [
        cut
        for cut in cuts
        if normalised(cut)[:SUBJECT_QUOTE].rstrip() in finding.subject
    ]
    return unmarked(agreed[-1] if agreed else cuts[0])


def _separators(message: str) -> list[int]:
    """Every position in the message where ``": `` starts."""
    found, start = [], 1
    while (at := message.find(_SEPARATOR, start)) != -1:
        found.append(at)
        start = at + 1
    return found


def passages(submission: Submission) -> str:
    """Everything in a submission that a policy may quote: its title,
    its description, its commit messages and the paths of its files."""
    return unmarked(
        "\n".join(
            [
                submission.title,
                submission.body,
                *(c.message for c in submission.commits),
                *(f.path for f in submission.files),
            ]
        )
    )


def same_passage(a: Finding, b: Finding) -> bool:
    """Whether two findings are the same finding.

    They are if they have the same policy and clause and the same
    subject. They are also if one's quotation contains the other's: a
    judge asked twice about the same words may quote a longer or a
    shorter piece of them, and that is not a new objection.
    """
    if (a.policy_id, a.clause) != (b.policy_id, b.clause):
        return False
    if a.subject == b.subject:
        return True
    ours, theirs = quoted(a), quoted(b)
    return bool(ours and theirs) and (ours in theirs or theirs in ours)


def stands(finding: Finding, text: str) -> bool | None:
    """Whether the words the finding quotes are in the text.

    None for a finding that quotes nothing.
    """
    quote = quoted(finding)
    if not quote:
        return None
    return quote in text
