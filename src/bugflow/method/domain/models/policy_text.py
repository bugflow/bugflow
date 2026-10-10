"""A judged policy as its file gives it.

A policy's prose is a file so that it can be read, diffed and published
on its own. What cannot be prose, which evidence the model is shown and
which text a quote must come from, is code in the judge, and the file
names which it wants by its ``evidence`` line.
"""

from collections.abc import Mapping
from dataclasses import dataclass

#: What a policy's ``evidence`` line may name: the part of a pull
#: request the model is shown. ``description`` is the title and the
#: description; ``scope`` adds the commit messages and file paths;
#: ``commits`` is each commit's message; ``patches`` is the diff.
EVIDENCE_KINDS = ("description", "scope", "commits", "patches")

#: The worst grade a finding may carry. A policy capped at warn is still
#: asked how bad each violation is; the answer is kept in its exchange,
#: and a fail is reported as a warning until the policy has earned the
#: grade.
CEILINGS = ("warn", "fail")


@dataclass(frozen=True)
class PolicyText:
    """One policy as its file gives it, before the judge wires it up."""

    policy_id: str
    subject: str
    summary: str
    #: The class of model this policy needs, not a model. Which model
    #: fills a class is configuration, and whether one is available at
    #: all decides whether the policy runs.
    model_class: str
    #: Which evidence the model is shown, one of ``EVIDENCE_KINDS``.
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
