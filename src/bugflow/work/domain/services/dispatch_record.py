"""The interface for reading every dispatch the journal recorded."""

from typing import Protocol

from bugflow.work.domain.models.journal import DispatchedWork


class DispatchRecordService(Protocol):
    def dispatched_work(self) -> list[DispatchedWork]:
        """Return every dispatch that started a run, oldest first.

        An entry that only says a runner was unavailable, or that an
        earlier answer was used again, started no run and is left out.

        A dispatch recorded without the runner's name for the work is
        still returned, with that name empty, so that a caller can count
        it as a run that cannot be asked about.
        """
        ...
