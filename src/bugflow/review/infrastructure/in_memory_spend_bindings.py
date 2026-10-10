"""Spend bindings kept in memory, for tests."""

from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)


def matches(
    scope: SpendScope, forge: str, repo: str, layer: str, agent: str
) -> bool:
    """Whether that scope covers this run. An empty part matches
    anything."""
    return (
        scope.forge in ("", forge)
        and scope.repo in ("", repo)
        and scope.layer in ("", layer)
        and scope.agent_id in ("", agent)
    )


class InMemorySpendBindings:
    def __init__(self) -> None:
        # Keyed by scope and denominator both: one scope holds an
        # allowance per event and one per period.
        self.bound: dict[tuple[SpendScope, str], SpendBinding] = {}

    def binding_for(
        self, forge: str, repo: str, layer: str, agent_id: str
    ) -> list[SpendBinding]:
        return [
            binding
            for binding in self.bindings()
            if matches(binding.scope, forge, repo, layer, agent_id)
        ]

    def bindings(self) -> list[SpendBinding]:
        return [
            binding
            for _, binding in sorted(
                self.bound.items(),
                key=lambda one: (
                    -one[0][0].parts,
                    one[0][0].forge,
                    one[0][0].repo,
                    one[0][0].layer,
                    one[0][0].agent_id,
                    one[0][1],
                ),
            )
        ]

    def revoke(self, scope: SpendScope, per: str) -> None:
        self.bound.pop((scope, per), None)

    def declare(self, binding: SpendBinding) -> None:
        self.bound[(binding.scope, binding.per)] = binding
