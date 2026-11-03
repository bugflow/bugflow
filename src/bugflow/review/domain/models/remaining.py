"""What an allowance has left in its period.

The dispatcher asks it before a run starts and a page shows it beside
the spend, and both must give the same answer, so there is one
definition and it is here.
"""

from dataclasses import dataclass
from datetime import datetime

from bugflow.review.domain.models.spend import Spent
from bugflow.review.domain.models.spend_binding import SpendBinding


@dataclass(frozen=True, kw_only=True)
class Remaining:
    """One allowance, set beside what its scope spent in one period.

    It states its scope and its period, because a figure for what is
    left means nothing without both: five dollars left this week on one
    repository is not five dollars left this month on its owner.
    """

    binding: SpendBinding
    #: What the scope spent over the period, which carries the period.
    spent: Spent

    @property
    def since(self) -> datetime:
        return self.spent.since

    @property
    def until(self) -> datetime:
        return self.spent.until

    @property
    def allowed_usd(self) -> float | None:
        """The allowance in dollars, or None where it sets no money
        limit."""
        return self.binding.budget.usd

    @property
    def left_usd(self) -> float | None:
        """What may still be spent in the period, never below zero, or
        None where there is no money limit.

        A scope that has spent past its allowance has nothing left, not
        a negative amount: the overspend is read from :attr:`over_usd`.
        """
        if self.allowed_usd is None:
            return None
        return max(0.0, self.allowed_usd - self.spent.usd)

    @property
    def over_usd(self) -> float:
        """How far the spend has gone past the allowance, or zero."""
        if self.allowed_usd is None:
            return 0.0
        return max(0.0, self.spent.usd - self.allowed_usd)

    @property
    def has_room(self) -> bool:
        """Whether another run may start under this allowance.

        A scope that has spent exactly its allowance has no room: the
        next run would spend past it, and a run cannot be stopped before
        it has spent anything.
        """
        return self.allowed_usd is None or self.spent.usd < self.allowed_usd
