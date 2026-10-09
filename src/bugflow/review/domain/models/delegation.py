"""A task handed to a runner, the handle to its run, and the run.

The work context has types for the same three things. These are this
context's own, with the same fields, so that this context imports
nothing from that one. An application copies one into the other.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from bugflow.shared.domain.values.budget import Budget

#: How a run stands. The words are the work context's.
TaskOutcome = Literal[
    "running",
    "completed",
    "stopped_short",
    "declined",
    "failed",
    "malformed",
]


@dataclass(frozen=True, kw_only=True)
class Task:
    """What a runner is asked to do, and what it may use."""

    instructions: str
    #: A directory the runner may read, or None.
    inputs: str | None = None
    #: A repository the runner may fetch, and the commit to read it at.
    repository: str = ""
    commit: str = ""
    #: The commit under review, when ``commit`` is its base.
    head: str = ""
    #: The JSON schema the answer must match, or None.
    artifact_schema: dict[str, Any] | None = None
    budget: Budget | None = None
    #: How many answers the runner may give before one that does not
    #: match the schema ends the run.
    attempts: int = 1


@dataclass(frozen=True, kw_only=True)
class Handle:
    """Identifies a dispatched run, so that a later step can come back
    to it."""

    runner: str
    fingerprint: str
    #: The runner's own name for the work.
    remote_id: str = ""
    #: The finished run, if the runner finished before it returned.
    run: "Run | None" = None
    budget: Budget | None = None
    artifact_schema: dict[str, Any] | None = None
    attempts: int = 1
    #: How long the run is worth waiting for, in seconds. Zero if the
    #: run is already finished.
    patience: float = 0.0

    @property
    def is_finished(self) -> bool:
        return self.run is not None


@dataclass(frozen=True, kw_only=True)
class RunParty:
    """One party to a run: who it was and what it did.

    The fields are plain text and not a fixed set of values. The work
    context decides which values there are, and this type must accept
    one that it adds.
    """

    kind: str
    role: str = "executed"
    identified_as: str = ""
    assurance: str = "none"


@dataclass(frozen=True, kw_only=True)
class Run:
    """What a run produced, and what it cost."""

    outcome: TaskOutcome
    #: The answer, in the shape the task asked for.
    artifact: dict[str, Any] = field(default_factory=dict)
    #: The messages of the run, if they are carried here and not stored.
    transcript: tuple[dict[str, Any], ...] = ()
    cost: dict[str, float] = field(default_factory=dict)
    runner: str = ""
    fingerprint: str = ""
    detail: str = ""
    #: Everyone who took part in the run.
    parties: tuple[RunParty, ...] = ()
    #: The person answerable for the result, if known.
    accountable: str = ""
    #: A reference to the full record of the run in the object store.
    workings: str = ""
    #: What was decided, for a run in which something was proposed and
    #: agreed.
    decision: dict[str, Any] = field(default_factory=dict)
    #: How many proposals were made before the answer.
    proposals: int = 0
