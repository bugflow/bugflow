"""The request and response of ``ProbeRetainedWriteUpsUseCase``.

The response never contains a write-up. It gives the length of each one
found and the key it was stored under.
"""

from collections import Counter
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

#: What was found for one recorded dispatch.
#:
#: - "no_remote_id": the record does not give the runner's name for the
#:   work, so the runner cannot be asked about it. This is a gap in the
#:   record. It does not mean the runner lost the run.
#: - "other_runner": the work was dispatched to a different runner from
#:   the one being asked.
#: - "unreachable": the runner was asked and did not return the run. It
#:   may have deleted it, or refused.
#: - "no_write_up": the runner returned the run, and it has no write-up.
#: - "write_up": the runner returned a write-up, and the use case was
#:   not set up to store it.
#: - "kept": the runner returned a write-up, and it was stored.
#: - "not_kept": the runner returned a write-up, and storing it failed.
#:   The runner still has it, so it can be tried again.
Outcome = Literal[
    "no_remote_id",
    "other_runner",
    "unreachable",
    "no_write_up",
    "write_up",
    "kept",
    "not_kept",
]

#: The outcomes in which the runner returned a write-up.
CARRIES: tuple[Outcome, ...] = ("write_up", "kept", "not_kept")
#: The outcomes in which the runner returned the run at all.
RETURNED: tuple[Outcome, ...] = ("no_write_up", *CARRIES)


class ProbeRetainedWriteUpsRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    # How many recorded dispatches to ask about, oldest first. Zero
    # means all of them.
    limit: int = 0


class Probe(BaseModel):
    """One recorded dispatch, and what was found for it."""

    model_config = ConfigDict(frozen=True)

    # When the work was dispatched.
    occurred_at: datetime
    repo: str
    pr_number: int | None
    agent_id: str
    remote_id: str
    runner: str
    outcome: Outcome
    # Something for a reader: what the runner said when it refused, why
    # the run stopped, or the name of the other runner.
    detail: str = ""
    # The length of the write-up, with white space at the ends removed.
    # Zero if no write-up was returned.
    characters: int = 0
    # The key the write-up is stored under. Empty unless it was kept.
    write_up_id: str = ""


class ProbeRetainedWriteUpsResponse(BaseModel):
    """What was found for each recorded dispatch, and counts of each
    kind of result."""

    model_config = ConfigDict(frozen=True)

    # The name of the runner that was asked.
    runner: str = ""
    probes: tuple[Probe, ...] = ()

    def _with(self, *outcomes: Outcome) -> tuple[Probe, ...]:
        return tuple(p for p in self.probes if p.outcome in outcomes)

    @property
    def read(self) -> int:
        """How many recorded dispatches were looked at."""
        return len(self.probes)

    @property
    def named(self) -> int:
        """How many of them give the runner's name for the work."""
        return len(self.probes) - len(self._with("no_remote_id"))

    @property
    def unnamed(self) -> int:
        """How many of them do not."""
        return len(self._with("no_remote_id"))

    @property
    def elsewhere(self) -> int:
        """How many were dispatched to a different runner."""
        return len(self._with("other_runner"))

    @property
    def returned(self) -> int:
        """How many runs the runner returned, with or without a
        write-up."""
        return len(self._with(*RETURNED))

    @property
    def recovered(self) -> int:
        """How many runs the runner returned with a write-up, whether or
        not it was then stored."""
        return len(self._with(*CARRIES))

    @property
    def kept(self) -> int:
        """How many write-ups were stored."""
        return len(self._with("kept"))

    @property
    def refused(self) -> int:
        """How many write-ups could not be stored."""
        return len(self._with("not_kept"))

    @property
    def empty(self) -> int:
        """How many runs the runner returned with no write-up."""
        return len(self._with("no_write_up"))

    @property
    def unreachable(self) -> int:
        """How many runs the runner did not return."""
        return len(self._with("unreachable"))

    @property
    def refusals(self) -> tuple[tuple[str, int], ...]:
        """What the runner said for the runs it did not return, with a
        count of each, most frequent first."""
        counted = Counter(p.detail for p in self._with("unreachable"))
        return tuple(counted.most_common())

    @property
    def oldest(self) -> datetime | None:
        """When the oldest run that returned a write-up was dispatched.
        With ``newest``, this shows how far back the runner still holds
        runs. None if no write-up was returned."""
        return min((p.occurred_at for p in self._with(*CARRIES)), default=None)

    @property
    def newest(self) -> datetime | None:
        """When the newest run that returned a write-up was
        dispatched."""
        return max((p.occurred_at for p in self._with(*CARRIES)), default=None)
