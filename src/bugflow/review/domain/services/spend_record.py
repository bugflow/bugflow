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

from bugflow.review.domain.models.spend import RunSpend, Spent


class SpendRecordService(Protocol):
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

    def spent_in_run(self, run_id: str) -> RunSpend:
        """Return what the run of that id has recorded spending so far.

        Asked while the run is going, to hold it to its own ceiling. A
        run that has recorded nothing answers zero over no facts, which
        is a run that has not spent rather than a run nobody asked
        about.
        """
        ...
