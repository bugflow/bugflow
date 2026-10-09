"""The evaluation regime: which rules are in force when a pull request is
observed."""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, kw_only=True)
class EvaluationRegime:
    """The rules in force, as much of them as this context needs.

    This context records each observation together with the version of
    the rules in force, and uses the version to tell whether a commit has
    already been reviewed under the current rules. It does not read the
    rules themselves.
    """

    #: The full text of the organisation's rules. This context does not
    #: read it. It is carried so that the code that needs it next does
    #: not have to load it again.
    doctrine_text: str
    #: An identifier for the exact judge (model and prompt) in use, or
    #: None.
    judge_fingerprint: str | None
    #: One version string for the whole regime. It changes when any part
    #: of the regime changes.
    version: str
    #: The parts the version was made from, by name, each with its own
    #: version.
    components: Mapping[str, str | None]
    #: Every installed review agent's own version, by agent id. Carried
    #: for the record, not read here.
    installed: Mapping[str, str] = field(default_factory=dict)
    #: The id of the review agent whose findings the judge reports.
    reporting_agent: str = ""
