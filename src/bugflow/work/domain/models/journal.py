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


def dispatched_from_entry(entry: JournalEntry) -> DispatchedWork:
    """Build a ``DispatchedWork`` from the journal entry of a dispatch.

    Every journal adapter uses this one function, so that they all read
    the entry's payload the same way.
    """
    payload: dict[str, Any] = entry.payload
    budget = payload.get("budget")
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
        agent_id=str(payload.get("agent_id") or ""),
        handle=AgentHandle(
            runner=str(payload.get("runner") or ""),
            fingerprint=str(payload.get("fingerprint") or ""),
            remote_id=str(payload.get("remote_id") or ""),
            # Only the limits the payload names are passed. One it does
            # not name takes the budget's default, not zero.
            budget=(
                Budget(
                    **{
                        key: float(value)
                        for key, value in budget.items()
                        if key in ("usd", "turns")
                    }
                )
                if isinstance(budget, dict) and budget
                else None
            ),
        ),
    )
