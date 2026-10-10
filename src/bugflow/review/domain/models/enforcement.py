"""What publishing may do for one repository, and the three profiles a
repository is bound to one of.

A profile says what reaches the forge and which verdict fails a commit
status. A repository nobody has bound is observed: findings are
journalled and nothing reaches the forge, which is what a deployment
does until someone decides otherwise.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

Failing = Literal["warn", "fail"]
ProfileName = Literal["observe", "advise", "gate"]


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


@dataclass(frozen=True, kw_only=True)
class EnforcementProfile:
    """One of the named profiles a repository is bound to."""

    name: ProfileName
    #: Whether comments, the label and commit statuses reach the forge.
    publishes: bool
    #: The least severity at which a governing agent's status is a
    #: failure. None: a status never fails, whatever was found.
    fails_at: Failing | None


OBSERVE = EnforcementProfile(name="observe", publishes=False, fails_at=None)
ADVISE = EnforcementProfile(name="advise", publishes=True, fails_at=None)
GATE = EnforcementProfile(name="gate", publishes=True, fails_at="fail")

#: The profiles by name.
PROFILES: Mapping[str, EnforcementProfile] = {
    profile.name: profile for profile in (OBSERVE, ADVISE, GATE)
}
