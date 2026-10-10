"""The interface for asking what this deployment will let a run spend.

A scope nobody bound is allowed nothing, and every binding that does
match applies, so a run must satisfy all of them.
"""

from typing import Protocol

from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)


class SpendBindingsService(Protocol):
    def binding_for(
        self, forge: str, repo: str, layer: str, agent_id: str
    ) -> list[SpendBinding]:
        """Return every allowance bound to this run, most specific
        first.

        All of them apply and a run must satisfy each: a binding on the
        repository and a binding on the reviewer are two limits and
        neither replaces the other.

        Empty where nothing matches, which allows nothing rather than
        allowing the usual amount: silence is not consent.
        """
        ...

    def bindings(self) -> list[SpendBinding]:
        """Return every ceiling this deployment holds, most specific
        first."""
        ...

    def revoke(self, scope: SpendScope, per: str) -> None:
        """Remove that scope's allowance for that denominator.

        Not the same as binding zero, which is an allowance that refuses
        everything. Removing leaves the scope to whatever wider
        allowances still cover it, and a scope no allowance covers
        spends nothing.
        """
        ...

    def declare(self, binding: SpendBinding) -> None:
        """Bind a ceiling to a scope, replacing what that scope held for
        the same denominator."""
        ...
