"""The interface for asking what this deployment has spent.

Read from the journal, which is where every cost was recorded: a
delegated run's session cost on the fact that collected it, and a
judge's call cost on the fact that made it.

One reader, because a dispatcher refusing a run and a page showing the
month have to agree.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from bugflow.review.domain.models.spend import (
    CostFact,
    RunCost,
    RunSpend,
    Spent,
)


class SpendRecordService(Protocol):
    def spent_by_run(
        self,
        since: datetime,
        until: datetime,
        forge: str = "",
        repo: str = "",
        layer: str = "",
        agent_id: str = "",
        owner: str = "",
    ) -> Sequence[RunCost]:
        """Return what each run spent in the window, split by layer,
        agent and kind of fact, latest first.

        The scope narrows the facts as it does for :meth:`spent`, so the
        rows for a scope sum to what :meth:`spent` answers for it: that
        is what lets a total be followed down to its runs.
        """
        ...

    def spent_by_scope(
        self,
        since: datetime,
        until: datetime,
        forge: str = "",
        repo: str = "",
        layer: str = "",
        agent_id: str = "",
        owner: str = "",
    ) -> Sequence[Spent]:
        """Return spend grouped by layer and agent in the window.

        The optional scope narrows the rows before grouping. Empty parts
        match anything, as they do for :meth:`spent`.
        """
        ...

    def spent(
        self,
        since: datetime,
        until: datetime,
        forge: str = "",
        repo: str = "",
        layer: str = "",
        agent_id: str = "",
        owner: str = "",
    ) -> Spent:
        """Return what the runs matching that scope cost between those
        times.

        An empty part of the scope matches anything, as a binding's
        does. An owner matches each of that owner's repositories. A
        window nothing ran in answers zero over no facts, which is not
        the same as a window nobody asked about.
        """
        ...

    def costs_in_run(
        self, workflow_id: str, run_id: str
    ) -> Sequence[CostFact]:
        """Return every costed fact the run recorded, oldest first.

        Over the run's whole life, as :meth:`spent_in_run` is, so the
        facts sum to what it answers for the run.
        """
        ...

    def spent_in_run(self, run_id: str) -> RunSpend:
        """Return what the run of that id has recorded spending so far.

        Asked while the run is going, to hold it to its own ceiling. A
        run that has recorded nothing answers zero over no facts, which
        is a run that has not spent rather than a run nobody asked
        about.
        """
        ...
