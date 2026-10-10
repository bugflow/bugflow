"""What an enforcement profile means, how a binding names one, and how
the two declarations read as the one value the use cases take."""

from bugflow.review.domain.models.enforcement import (
    ADVISE,
    GATE,
    OBSERVE,
    Enforcement,
)
from bugflow.review.domain.models.withholding import Withholding
from bugflow.review.infrastructure.declared_enforcement import (
    DeclaredEnforcement,
)
from bugflow.review.infrastructure.in_memory_enforcement import (
    InMemoryEnforcement,
)
from bugflow.review.infrastructure.in_memory_withholding import (
    InMemoryWithholding,
)


def test_observe_publishes_nothing_and_fails_nothing() -> None:
    assert OBSERVE.publishes is False
    assert OBSERVE.fails_at is None


def test_advise_publishes_and_no_severity_fails() -> None:
    assert ADVISE.publishes is True
    assert ADVISE.fails_at is None


def test_gate_publishes_and_a_fail_fails() -> None:
    assert GATE.publishes is True
    assert GATE.fails_at == "fail"


def test_a_repository_not_bound_resolves_to_observe() -> None:
    """The default, and the common case: a repository nobody has
    decided about publishes nothing."""
    enforcement = InMemoryEnforcement()
    enforcement.bind("github", "example/bound", ADVISE)

    assert enforcement.profile_for("github", "example/bound") is ADVISE
    assert enforcement.profile_for("github", "example/unbound") is OBSERVE
    assert enforcement.profile_for("forgejo", "example/bound") is OBSERVE


def test_the_declared_profile_and_share_read_as_one_enforcement() -> None:
    profiles = InMemoryEnforcement()
    profiles.bind("github", "example/gated", GATE)
    withholding = InMemoryWithholding()
    withholding.declare(
        Withholding(forge="github", repo="example/gated", share=0.5)
    )
    declared = DeclaredEnforcement(profiles, withholding)

    assert declared.enforcement_for("github", "example/gated") == Enforcement(
        publishes=True, fails_at="fail", withholds=0.5
    )
    assert declared.enforcement_for("github", "example/other") == Enforcement(
        publishes=False, fails_at=None, withholds=0.0
    )


def test_with_no_share_declared_anywhere_nothing_is_withheld() -> None:
    profiles = InMemoryEnforcement()
    profiles.bind("github", "example/advised", ADVISE)

    enforcement = DeclaredEnforcement(profiles).enforcement_for(
        "github", "example/advised"
    )
    assert (enforcement.publishes, enforcement.withholds) == (True, 0.0)
