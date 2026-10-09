"""What publishing may do for one repository."""

from dataclasses import dataclass
from typing import Literal

Failing = Literal["warn", "fail"]


@dataclass(frozen=True, kw_only=True)
class Enforcement:
    #: Whether comments, the label and commit statuses are written to
    #: the forge at all.
    publishes: bool
    #: The lowest verdict that makes a commit status fail. None means no
    #: verdict does: every status is advice.
    fails_at: Failing | None
    #: The share of warnings, from 0 to 1, that are kept out of the
    #: pull request on purpose. Comparing what happens to a warning
    #: nobody saw with one somebody could have seen shows whether
    #: warnings are acted on. The default, 0, keeps none out.
    withholds: float = 0.0


def fails(enforcement: Enforcement, verdict: str | None) -> bool:
    """Whether a verdict makes the commit status fail for this
    repository."""
    if enforcement.fails_at is None or verdict is None:
        return False
    return verdict == "fail" or (
        verdict == "warn" and enforcement.fails_at == "warn"
    )
