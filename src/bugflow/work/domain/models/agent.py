"""A task handed to a runner, the handle that identifies its run, and
what the run produced."""

from dataclasses import dataclass, field
from typing import Any, Literal

from bugflow.shared.domain.values.budget import Budget

#: How a run stands.
#:
#: - "running": it has not finished yet.
#: - "completed": it finished and gave an answer in the right shape.
#:   This says the run ended properly. It does not say the answer is
#:   good; that is judged elsewhere.
#: - "stopped_short": it ended before answering, because it reached a
#:   limit on turns, money or time, or because it gave up.
#: - "declined": it would not do the work it was asked to do.
#: - "failed": it broke.
#: - "malformed": it answered, but no answer matched the shape the task
#:   asked for, however often it was asked. Its first answer is kept as
#:   the write-up, so that it is not lost.
#:
#: None of these means "it never started". That case is an error,
#: ``AgentUnavailableError``.
RunOutcome = Literal[
    "running",
    "completed",
    "stopped_short",
    "declined",
    "failed",
    "malformed",
]


@dataclass(frozen=True, kw_only=True)
class AgentHandle:
    """Identifies a dispatched run, so that a later step can wait for it
    and collect what it produced.

    A handle is plain data. A workflow passes it between steps that may
    run in different processes, so it cannot depend on anything held in
    memory by the adapter that made it.

    Some runners finish the work before ``dispatch`` returns. Their
    handle carries the finished run in ``run``. Others carry on working
    afterwards. Their handle names the work in ``remote_id``.
    """

    #: The name of the runner that was given the work.
    runner: str
    #: A hash of the settings that decide how the runner behaves.
    fingerprint: str
    #: The runner's own name for the work, such as a session id. Empty
    #: for a runner that finished before ``dispatch`` returned.
    remote_id: str = ""
    #: The finished run, for a runner that finished before ``dispatch``
    #: returned. None for one that is still working.
    run: "AgentRun | None" = None
    #: What the run may spend, as the adapter understood it. Kept so
    #: that the limit can be read beside the cost afterwards.
    budget: Budget | None = None
    #: The shape the answer must have and how many answers the run may
    #: give, copied from the task so that collecting can check the
    #: answer without the task.
    artifact_schema: dict[str, Any] | None = None
    attempts: int = 1
    #: How long, in seconds, the adapter thinks this run is worth
    #: waiting for. A hosted model takes minutes; a person may take
    #: days. Zero for a runner that already finished.
    patience: float = 0.0

    @property
    def is_finished(self) -> bool:
        """True if the run finished before ``dispatch`` returned, so
        there is nothing to wait for."""
        return self.run is not None


@dataclass(frozen=True, kw_only=True)
class AgentTask:
    """What a runner is asked to do, and what it may use."""

    #: The instructions. These are written by whoever dispatches the
    #: task. They must never be built from anything the material under
    #: review contains, since that material is not trusted.
    instructions: str
    #: A directory the runner may read, prepared by the caller. None if
    #: the task needs no files.
    inputs: str | None = None
    #: A repository the runner may read, by the name its forge gives it,
    #: and the commit to read it at. Used by a runner that can fetch a
    #: repository itself. Empty otherwise.
    repository: str = ""
    commit: str = ""
    #: The commit under review, when ``commit`` is a different one. A
    #: runner given the base commit fetches this one and compares.
    head: str = ""
    #: The shape the answer must have, as a JSON schema. A run counts as
    #: completed only if its answer matches.
    artifact_schema: dict[str, Any] | None = None
    #: How many answers the runner may give before one that does not
    #: match the schema ends the run as "malformed". One means no second
    #: try.
    attempts: int = 1
    #: What the run may spend before it is stopped.
    budget: Budget | None = None


#: What kind of party took part in a run. A hosted model is one party. A
#: person working with a coding agent is two.
PartyKind = Literal["person", "agent"]

#: What a party did. A run in which nothing was proposed has one party,
#: which executed.
PartyRole = Literal["executed", "proposed", "agreed"]

#: How far a party's identity can be relied on.
#:
#: - "verified": the server knows it for itself. It started the run, or
#:   the identity provider confirmed who the person is.
#: - "self_reported": the party said so, and nothing confirms it.
#: - "none": nothing established who the party is.
Assurance = Literal["verified", "self_reported", "none"]


@dataclass(frozen=True, kw_only=True)
class Party:
    """One party to a run: who it was, what it did, and how well its
    identity is known."""

    kind: PartyKind
    role: PartyRole = "executed"
    #: The party's name: a runner's name for a model, or the identity
    #: provider's id for a person. Empty if not known.
    identified_as: str = ""
    assurance: Assurance = "none"


@dataclass(frozen=True, kw_only=True)
class AgentRun:
    """What a run produced, and what it cost."""

    outcome: RunOutcome
    #: The answer, in the shape the task asked for, when the run
    #: completed. A malformed run has its first answer under the key
    #: ``write_up``. Empty if the run produced nothing usable.
    artifact: dict[str, Any] = field(default_factory=dict)
    #: The messages of the run as they happened. Superseded by
    #: ``workings`` below, which refers to the record instead of
    #: carrying it.
    transcript: tuple[dict[str, Any], ...] = ()
    #: What the run cost, as the adapter reported it. The keys are the
    #: adapter's own, such as dollars, tokens or turns.
    cost: dict[str, float] = field(default_factory=dict)
    #: The runner that did the work and the hash of its settings.
    runner: str = ""
    fingerprint: str = ""
    #: Anything the adapter wants a reader to know about the outcome.
    detail: str = ""
    #: Everyone who took part. Empty for a run recorded before parties
    #: were kept.
    parties: tuple[Party, ...] = ()
    #: The person answerable for the result: for a person working with
    #: an agent, the person who agreed to it; for an unattended run,
    #: whoever owns the configuration that started it. Empty if not
    #: known.
    accountable: str = ""
    #: Where the full record of the run is kept in the object store.
    #: Only the reference is carried here, because a workflow engine
    #: records everything passed between steps and the full record is
    #: large.
    workings: str = ""
    #: What was decided, for a run in which something was proposed and
    #: agreed. Empty otherwise.
    decision: dict[str, Any] = field(default_factory=dict)
    #: How many proposals were made before the answer. Zero for a run
    #: that worked alone.
    proposals: int = 0
