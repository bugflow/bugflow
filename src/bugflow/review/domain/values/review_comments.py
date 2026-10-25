"""The text of the comments a reviewer posts on a pull request.

Each reviewer posts comments of its own. A comment starts with the
reviewer's name and its verdict. It has nothing in it that is only for
a machine: ids, hashes and the name of the model are in the journal.

There are three kinds of comment:

- ``findings_comment``, from a reviewer that judges or checks. Each
  finding is one folded line: a sentence that names the clause it
  breaks, linked to the clause's page on the gnome's site, and where
  the passage is. Unfolded, it shows the passage at fault, quoted, and
  what is wrong with it. Findings that break one clause stand
  together, the most severe clause first. What has been fixed is given
  as a count, with the passages folded away.
- ``clean_comment``, the first comment of such a reviewer when it found
  nothing.
- ``agent_comment``, from a checkout agent. It is the agent's note to
  the author. If there is no note fit to show, the whole write-up is
  folded under the verdict.

Every function here only builds text from what it is given.
"""

import html
import re
from collections.abc import Mapping, Sequence

from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.review import ReviewNote, ReviewStatus

# The order findings are shown in, and the words used for each severity.
_SEVERITY_ORDER = {"fail": 0, "warn": 1, "info": 2}
_SEVERITY_WORD = {"fail": "Failure", "warn": "Warning", "info": "Note"}
_COUNTED = {"fail": "failure", "warn": "warning", "info": "note"}
# How a finding of each severity relates the passage to its clause.
_VERB = {"fail": "Violates", "warn": "Falls short of", "info": "Bears on"}

# A commit's short or full id, which a finding's subject may be on its
# own.
_COMMIT_ID = re.compile(r"^[0-9a-f]{7,40}$")

# The words a checkout agent's comment opens with, for each verdict.
_VERDICT = {
    "pass": "nothing to raise",
    "warn": "something to consider",
    "fail": "a problem to fix",
}

# A finding's message when it quotes: the words in double quotes, then
# a colon and what is wrong with them.
_QUOTED = re.compile(r'^"(?P<quote>.+?)": (?P<said>.*)$', re.DOTALL)

# The name of a clause that has one, as in "**RULE-4. One reason.** A
# commit ...".
_CLAUSE_NAME = re.compile(r"^\*\*[A-Z]+-\d+\. (?P<name>[^*]+?)\.\*\*")


def reviewer_name(agent_id: str) -> str:
    """The name a reviewer's comment opens with: the agent id "prose"
    gives "Prose review".
    """
    return f"{agent_id[:1].upper()}{agent_id[1:]} review"


def clause_page(site: str, clause: str) -> str:
    """The address of a clause's page on a gnome's site, which renders
    the doctrine as one page with a section for each clause, anchored
    by the clause's id. Empty if the gnome has no site.
    """
    if not site:
        return ""
    return f"{site.rstrip('/')}/doctrine/#{clause}"


def _count(n: int, noun: str) -> str:
    """A number and a noun, made plural if the number is not one."""
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _counts(findings: Sequence[Finding]) -> str:
    """How many findings there are of each severity, as words: "1
    failure, 2 warnings".
    """
    by = {s: sum(f.severity == s for f in findings) for s in _COUNTED}
    return ", ".join(_count(n, _COUNTED[s]) for s, n in by.items() if n)


def _where(subject: str) -> str:
    """Where a passage is, from a finding's subject.

    A subject says where and then quotes the passage: 'description
    "..."' or 'commit 1a2b3c4 "..."'. The part before the quotation
    is returned. An empty one is "pull request".
    """
    where = subject.split(' "', 1)[0].strip()
    return where or "pull request"


def passage_of(finding: Finding) -> tuple[str, str, str]:
    """A finding as three parts: where the passage is, the passage, and
    what is wrong with it.

    If the finding's message quotes nothing, the passage is empty and
    the whole message is the third part.
    """
    quoted = _QUOTED.match(finding.message)
    if quoted is None:
        return _where(finding.subject), "", finding.message.strip()
    return (
        _where(finding.subject),
        quoted.group("quote").strip(),
        quoted.group("said").strip(),
    )


def _rule_name(
    finding: Finding,
    summaries: Mapping[str, str],
    clauses: Mapping[str, str],
) -> str:
    """The name of the clause a finding breaks.

    The name is the clause's own if it has one. Otherwise it is the
    policy's summary. Empty when neither is known: a clause's id is
    for a machine, and is not shown in its place.
    """
    named = _CLAUSE_NAME.match(clauses.get(finding.clause, ""))
    if named:
        return named.group("name")
    return summaries.get(finding.policy_id, "").strip().rstrip(".")


def _rule(name: str, page: str) -> str:
    """A clause as a finding names it: a link to its page, or its name
    in bold when the gnome has no site to link to. In HTML, because
    the sentence is a fold's summary, and a forge renders no Markdown
    there.
    """
    shown = html.escape(name)
    if page:
        return f'<a href="{html.escape(page, quote=True)}">{shown}</a>'
    return f"<b>{shown}</b>"


def _verdict(finding: Finding, rule: str, where: str) -> str:
    """The sentence that relates a passage to its clause: "Violates
    <a>One reason</a> in commit 1a2b3c4." With no clause to name, the
    severity stands alone: "<b>Failure</b> in commit 1a2b3c4."
    """
    if rule:
        return f"{_VERB[finding.severity]} {rule} {_at(where)}."
    return f"<b>{_SEVERITY_WORD[finding.severity]}</b> {_at(where)}."


def _shown(finding: Finding, quote: str) -> str:
    """A passage as the comment shows it.

    A judged finding's passage is a quotation the judge chose, and is
    shown whole. A checked finding's passage is a fixed number of
    characters either side of what was found, so its first and last
    words are usually cut off. Those two words are dropped and an
    ellipsis put in their place.
    """
    words = quote.split(" ")
    if finding.judged_by is not None or len(words) <= 4:
        return quote
    return "…" + " ".join(words[1:-1]) + "…"


def _quoted(passage: str) -> str:
    """A passage as a block quotation, every line of it."""
    return "\n".join(f"> {line}".rstrip() for line in passage.splitlines())


def _at(where: str) -> str:
    """The words that say where a passage is: "in the description",
    "in the title", "in the pull request" or "in commit 1a2b3c4".
    """
    if where in ("description", "title", "pull request"):
        return f"in the {where}"
    if _COMMIT_ID.match(where):
        return f"in commit {where}"
    return f"in {where}"


def _fold(summary: str, body: str) -> list[str]:
    """The lines of a folded section, which a reader opens by clicking
    its summary.
    """
    return [
        f"<details><summary>{summary}</summary>",
        "",
        body.strip(),
        "",
        "</details>",
        "",
    ]


def findings_comment(
    marker: str,
    agent_id: str,
    raised: Sequence[Finding],
    fixed: Sequence[Finding],
    standing: Sequence[Finding],
    summaries: Mapping[str, str] | None = None,
    clauses: Mapping[str, str] | None = None,
    rejudged: bool = False,
    site: str = "",
) -> str:
    """Build a reviewer's comment about its findings.

    ``raised`` are the findings that are new. ``fixed`` are those that
    are gone. ``standing`` is every finding the reviewer holds against
    the pull request's last commit and has shown the author, now or
    before. The first line counts ``standing``, so that the author
    reads the present state first.

    ``summaries`` gives each policy's summary by policy id, and
    ``clauses`` the text of each clause by clause id. ``site`` is the
    address the reviewer's gnome publishes its pages at, which each
    finding links the clause it cites to; empty, and the clause is
    named and not linked.

    ``rejudged`` is True when the pull request did not change and the
    reviewer did. The comment then says so, because nothing the author
    did explains what follows.
    """
    summaries = summaries or {}
    clauses = clauses or {}
    name = reviewer_name(agent_id)
    counted = _counts(standing)
    lines = [
        marker,
        "",
        f"**{name}:** {counted}."
        if counted
        else f"**{name}: nothing to raise.**",
        "",
    ]
    if rejudged:
        lines += [
            "The pull request has not changed since the last review; this "
            "reviewer has, and read the same commit again.",
            "",
        ]

    # The findings of each clause together, the most severe first. Each
    # is one fold: the clause it breaks and where, and beneath, the
    # passage, quoted, and what is wrong.
    ordered = sorted(raised, key=lambda f: _SEVERITY_ORDER[f.severity])
    by_rule: dict[tuple[str, str], list[Finding]] = {}
    for f in ordered:
        by_rule.setdefault((f.policy_id, f.clause), []).append(f)

    for found in by_rule.values():
        name = _rule_name(found[0], summaries, clauses)
        rule = _rule(name, clause_page(site, found[0].clause)) if name else ""
        for f in found:
            where, quote, said = passage_of(f)
            inside = []
            if quote:
                inside.append(_quoted(_shown(f, quote)))
            if said:
                inside.append(f"{said[:1].upper()}{said[1:]}")
            sentence = _verdict(f, rule, where)
            if inside:
                lines += _fold(sentence, "\n\n".join(inside))
            else:
                lines += [sentence, ""]

    # The first line counts everything that stands. What is new is
    # listed above, so the rest is accounted for here.
    earlier = len(standing) - len(raised)
    if earlier == 1:
        lines += [
            "One more, raised earlier, still stands."
            if raised
            else "One, raised earlier, still stands.",
            "",
        ]
    elif earlier > 1:
        lines += [
            f"{earlier} more, raised earlier, still stand."
            if raised
            else f"{earlier}, raised earlier, still stand.",
            "",
        ]

    gone = list(dict.fromkeys(passage_of(f)[1] or f.message for f in fixed))
    if gone:
        listed = "\n".join(f'- "{g}"' for g in gone)
        lines += _fold(
            f"{_count(len(gone), 'passage')} fixed since the last review",
            listed,
        )
    return "\n".join(lines).rstrip("\n") + "\n"


def clean_comment(
    marker: str,
    agent_id: str,
    read: str,
    aims: Sequence[str] = (),
) -> str:
    """Build a reviewer's first comment on a pull request it found
    nothing in.

    ``read`` is a sentence saying what the reviewer read. ``aims`` say
    what it read for, and are folded beneath.
    """
    lines = [
        marker,
        "",
        f"**{reviewer_name(agent_id)}: nothing to raise.** {read}",
        "",
    ]
    if aims:
        lines += _fold(
            "What it was read for",
            "\n".join(f"- {aim.strip().rstrip('.')}" for aim in aims),
        )
    return "\n".join(lines).rstrip("\n") + "\n"


def agent_comment(marker: str, status: ReviewStatus, note: ReviewNote) -> str:
    """Build a checkout agent's comment: its verdict, and its note to
    the author.

    A note of one paragraph follows the verdict on the same line. A
    longer note starts on the line below. If there is no note, the
    write-up is folded under the verdict.
    """
    head = f"**{reviewer_name(note.agent_id)}: {_VERDICT[status]}.**"
    lines = [marker, ""]
    said = note.note.strip()
    if said and "\n" not in said:
        lines += [f"{head} {said}", ""]
    elif said:
        lines += [head, "", said, ""]
    else:
        lines += [head, ""]
        if note.write_up.strip():
            lines += _fold("The review", note.write_up)
    return "\n".join(lines).rstrip("\n") + "\n"
