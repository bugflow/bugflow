"""A judged policy as its file gives it.

A policy's prose is a file so that it can be read, diffed and published
on its own. What cannot be prose, which evidence the model is shown and
which text a quote must come from, is code in the judge, and the file
names which it wants by its ``evidence`` line.
"""

from collections.abc import Mapping
from dataclasses import dataclass

#: The subjects a policy's ``evidence`` line may name, as ``KIND/PART``.
#: A pull request's parts: ``description`` is the title and the
#: description; ``scope`` adds the commit messages and file paths;
#: ``commits`` is each commit's message; ``patches`` is the diff. A
#: document's ``file`` is one document the pull request changes, as the
#: patch shows it after the change. A document's ``glossary`` is each
#: changed document in the same way, then the glossary files of the
#: deployment in force. A scope's ``canon`` is every document of a
#: scope, which a pull request judge does not render.
SUBJECTS = (
    "pull-request/description",
    "pull-request/scope",
    "pull-request/commits",
    "pull-request/patches",
    "document/file",
    "document/glossary",
    "scope/canon",
)

#: The subjects a pull request judge renders. A declaration naming a
#: policy whose subject is not among them is refused.
JUDGED_SUBJECTS = SUBJECTS[:6]

#: The parts of a pull request, which an ``evidence`` line may name
#: alone: ``description`` is ``pull-request/description``.
EVIDENCE_KINDS = ("description", "scope", "commits", "patches")

#: How a policy is answered: by a model given its instructions, or by a
#: check, code that needs no model.
IMPLEMENTATIONS = ("judge", "check")

#: The worst grade a finding may carry. A policy capped at warn is still
#: asked how bad each violation is; the answer is kept in its exchange,
#: and a fail is reported as a warning until the policy has earned the
#: grade.
CEILINGS = ("warn", "fail")


def subject_of(value: str) -> str:
    """The subject an ``evidence`` line names: one of ``SUBJECTS``, or a
    pull request's part alone, which names that part's subject.

    Raises ``ValueError`` for anything else.
    """
    if value in EVIDENCE_KINDS:
        return f"pull-request/{value}"
    if value in SUBJECTS:
        return value
    raise ValueError(
        f"evidence {value!r} is not a subject; the subjects are "
        f"{', '.join(SUBJECTS)}"
    )


@dataclass(frozen=True)
class PolicyText:
    """One policy as its file gives it, before the judge wires it up."""

    policy_id: str
    subject: str
    summary: str
    #: The class of model this policy needs, not a model. Which model
    #: fills a class is configuration, and whether one is available at
    #: all decides whether the policy runs. ``none`` for a checked
    #: policy.
    model_class: str
    #: The subject the model is shown, one of ``SUBJECTS``.
    evidence: str
    quotable_name: str
    graded: bool
    quotes_code: bool
    #: The doctrine clauses the policy cites, by id, each with the name
    #: the policy gives it.
    clauses: Mapping[str, str]
    instructions: str
    calibration: str
    #: The worst grade a finding may carry, one of ``CEILINGS``.
    ceiling: str = "fail"
    #: How the policy is answered, one of ``IMPLEMENTATIONS``. A checked
    #: policy's instructions are for a person; a server answers it with
    #: the check its manifest names, and never with a model.
    implemented: str = "judge"

    @property
    def checked(self) -> bool:
        """Whether a check answers this policy, and not a model."""
        return self.implemented == "check"
