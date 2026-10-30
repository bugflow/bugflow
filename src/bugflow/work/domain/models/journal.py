"""What the journal says about work that was dispatched.

When a run is dispatched, a fact is written to the journal. These types
are what is read back from those facts.
"""

from dataclasses import dataclass

from bugflow.shared.domain.values.correlation import Correlation


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
