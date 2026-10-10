"""The corpus: everything that decides what an evaluation finds.

The deployment's version changes whenever the doctrine or the judge
changes, so a change to either shows in the record as a change of the
rules in force and not as unexplained drift.

Each installed reviewer has a version of its own besides, over its own
prose and the pinned thing that runs it, so that editing one reviewer's
prompt moves the version recorded on its findings and on nobody else's.
"""

import hashlib
import json
from dataclasses import dataclass, field

from bugflow.method.domain.models.doctrine import Doctrine

#: The runner a reviewer that is only prose names: the judge, which is
#: not dispatched at a checkout. The reviewer naming it is the one whose
#: policies a judged or a checked finding belongs to.
JUDGE_RUNNER = "judge"


def _digest(components: dict[str, str | None]) -> str:
    canonical = json.dumps(components, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


@dataclass(frozen=True, kw_only=True)
class AgentCorpus:
    """One installed reviewer's own corpus: what decides what it finds."""

    agent_id: str
    #: A hash of the reviewer's own prose: its manifest, its policies and
    #: its doctrine. Contents and not paths, so moving a directory moves
    #: no version.
    prose: str
    #: The runner its manifest names.
    runner: str
    #: A fingerprint of the pinned thing that runner runs it with: the
    #: judge's model and adapter source, or a checkout runner's. None if
    #: this server has no such runner set up.
    pinned: str | None
    #: A fingerprint of the code that answers this reviewer's checked
    #: policies. A checked policy is answered by a function and not by
    #: what the runner runs, so the runner's fingerprint says nothing
    #: about it. None for a reviewer with no checked policy.
    checks: str | None = None

    def components(self) -> dict[str, str | None]:
        """The four things the version is made from."""
        return {
            "prose": self.prose,
            "runner": self.runner,
            "pinned": self.pinned,
            "checks": self.checks,
        }

    @property
    def version(self) -> str:
        """The first 12 hexadecimal characters of a hash of the
        components."""
        return _digest(self.components())


@dataclass(frozen=True, kw_only=True)
class Corpus:
    doctrine: Doctrine
    #: A fingerprint of the judge's model and adapter source. None if no
    #: judge is set up.
    judge: str | None
    #: Every installed reviewer, in id order. Empty for a server with no
    #: reviewer installed.
    agents: tuple[AgentCorpus, ...] = field(default_factory=tuple)

    def components(self) -> dict[str, str | None]:
        """The two things the version is made from."""
        return {
            "doctrine": self.doctrine.version,
            "judge": self.judge,
        }

    @property
    def version(self) -> str:
        """The deployment's version: the doctrine and the judge.

        It is what an evaluation runs under as a whole, and what decides
        whether a commit has been judged already. No reviewer's prose is
        in it, so installing or editing one changes only that reviewer's
        own version.
        """
        return _digest(self.components())

    @property
    def installed(self) -> dict[str, str]:
        """Every installed reviewer's own corpus version, by id."""
        return {agent.agent_id: agent.version for agent in self.agents}

    @property
    def reporting_agent(self) -> str:
        """The reviewer the judge answers for, whose policies a judged or
        a checked finding belongs to. Empty if none is installed."""
        for agent in self.agents:
            if agent.runner == JUDGE_RUNNER:
                return agent.agent_id
        return ""

    def version_for(self, agent_id: str) -> str:
        """The version this reviewer's findings are recorded under: its
        own if it is installed, and the deployment's otherwise."""
        for agent in self.agents:
            if agent.agent_id == agent_id:
                return agent.version
        return self.version
