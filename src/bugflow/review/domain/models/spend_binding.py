"""What this deployment will let a run spend, and on what.

The ceiling itself is a ``Budget``, which is the shared vocabulary for
money and turns. What is declared here is which ceiling applies to
what: a scope, and the budget bound to it.
"""

from dataclasses import dataclass

from bugflow.shared.domain.values.budget import Budget


@dataclass(frozen=True, kw_only=True)
class SpendScope:
    """What a ceiling applies to.

    Any part may be left open, and an open part matches anything. A row
    scoped to a repository alone caps everything that reads it; a row
    scoped to a layer and an agent caps that agent's run on that layer
    in every repository. The most specific row that matches is the one
    that applies, so a general ceiling can be set once and one
    repository given its own.
    """

    #: The forge and repository, as the journal holds them, or empty for
    #: every repository.
    forge: str = ""
    repo: str = ""
    #: The pace layer, a name the topology declares, or empty for every
    #: layer.
    layer: str = ""
    #: The reviewer, or empty for every reviewer.
    agent_id: str = ""

    @property
    def parts(self) -> int:
        """How many parts of the scope are named.

        What makes one row more specific than another: a row naming a
        repository and an agent beats one naming the repository alone.
        """
        return sum(
            1
            for one in (self.forge, self.repo, self.layer, self.agent_id)
            if one
        )


@dataclass(frozen=True, kw_only=True)
class SpendBinding:
    """One ceiling, what it applies to, and what shares it."""

    scope: SpendScope
    budget: Budget
    #: What shares the allowance: a cadence the topology declares, as
    #: :attr:`SpendScope.layer` is a layer it declares. The binding
    #: holds the name and knows nothing about which names exist,
    #: because a cadence is the method's and a second vocabulary for it
    #: drifts from the first.
    #:
    #: Per event unless said otherwise, which is the ceiling a run is
    #: already held to and the only one a vendor can enforce. A cadence
    #: with a clock is enforced by asking before a run starts, because
    #: it has to be measured from what was recorded.
    per: str = "event"
