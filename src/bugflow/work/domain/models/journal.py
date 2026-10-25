"""What the journal says about work that was dispatched.

When a run is dispatched, a fact is written to the journal. These types
are what is read back from those facts.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.budget import Budget
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.work.domain.models.agent import AgentHandle


@dataclass(frozen=True, kw_only=True)
class DispatchedRun:
    """Which workflow run dispatched a piece of work, and for which
    agent.

    A completion names only the runner and the runner's name for the
    work. This is how the completion is matched to the workflow run that
    is waiting for it.
    """

    correlation: Correlation
    agent_id: str
    #: What the dispatch was about, so that a fact recorded about the
    #: run can be filed in the same place.
    forge: str = ""
    repo: str = ""
    pr_number: int | None = None
    commit_sha: str | None = None


@dataclass(frozen=True, kw_only=True)
class DispatchedWork:
    """One dispatch as the journal recorded it: the handle of the run,
    and what the dispatch was about.

    The handle is rebuilt only from what was recorded. A record with no
    remote id gives a handle with none.
    """

    correlation: Correlation
    occurred_at: datetime
    forge: str
    repo: str
    pr_number: int | None
    commit_sha: str | None
    corpus_version: str | None
    agent_id: str
    handle: AgentHandle


def dispatched_from(
    entry: JournalEntry,
    *,
    agent_id: str | None,
    runner: str | None,
    fingerprint: str | None,
    remote_id: str | None,
    budget_usd: float | None,
    budget_turns: float | None,
) -> DispatchedWork:
    """Build a ``DispatchedWork`` from the envelope of a dispatch and the
    columns of its row (ADR 007).

    Every journal adapter uses this one function, so that they all read
    a dispatch the same way: the Postgres adapter from the dispatch's
    table, the in-memory one from the payload it keeps.
    """
    # Only the limits recorded are passed. One not recorded takes the
    # budget's default, not zero.
    limits = {
        key: float(value)
        for key, value in (("usd", budget_usd), ("turns", budget_turns))
        if value is not None
    }
    return DispatchedWork(
        correlation=Correlation(
            workflow_id=entry.workflow_id, run_id=entry.run_id
        ),
        occurred_at=entry.occurred_at,
        forge=entry.forge,
        repo=entry.repo,
        pr_number=entry.pr_number,
        commit_sha=entry.commit_sha,
        corpus_version=entry.corpus_version,
        agent_id=agent_id or "",
        handle=AgentHandle(
            runner=runner or "",
            fingerprint=fingerprint or "",
            remote_id=remote_id or "",
            budget=Budget(**limits) if limits else None,
        ),
    )


def dispatched_from_entry(entry: JournalEntry) -> DispatchedWork:
    """Build a ``DispatchedWork`` from the payload a dispatch's entry was
    written with, as the in-memory journal keeps it."""
    payload: dict[str, Any] = entry.payload
    budget = payload.get("budget")
    limits = budget if isinstance(budget, dict) else {}
    return dispatched_from(
        entry,
        agent_id=_text(payload.get("agent_id")),
        runner=_text(payload.get("runner")),
        fingerprint=_text(payload.get("fingerprint")),
        remote_id=_text(payload.get("remote_id")),
        budget_usd=_number(limits.get("usd")),
        budget_turns=_number(limits.get("turns")),
    )


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def _number(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]
