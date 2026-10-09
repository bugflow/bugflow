"""A helper that builds journal entries about one pull request.

A use case that works on a pull request usually records several facts
about it in one run. They all share the pull request, the run, and the
time. A ``Recorder`` is given those once and then builds each entry from
just the fact's type, a key and its details.
"""

from datetime import datetime
from typing import Any

from bugflow.shared.domain.models.journal_entry import JournalEntry, event_id
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class Recorder:
    """Builds journal entries for one pull request in one workflow run.

    ``corpus_version`` is the version of the review rules in effect, or
    None. ``occurred_at`` is the time every entry is given.
    """

    def __init__(
        self,
        ref: PullRequestRef,
        correlation: Correlation,
        corpus_version: str | None,
        occurred_at: datetime,
    ) -> None:
        self._ref = ref
        self._correlation = correlation
        self._corpus_version = corpus_version
        self._occurred_at = occurred_at

    def entry(
        self,
        event_type: str,
        key: str,
        payload: dict[str, Any],
        commit_sha: str | None = None,
        agent_id: str | None = None,
        corpus_version: str | None = None,
    ) -> JournalEntry:
        """Build one entry.

        ``key`` tells this fact apart from others of the same type in the
        same run; the entry's id is made from the run, the type and the
        key. ``agent_id`` is for a fact that belongs to one review agent.
        ``corpus_version``, if given, replaces the recorder's own for
        this entry.
        """
        return JournalEntry(
            event_id=event_id(self._correlation, event_type, key),
            occurred_at=self._occurred_at,
            event_type=event_type,
            forge=self._ref.forge,
            repo=f"{self._ref.owner}/{self._ref.repo}",
            pr_number=self._ref.number,
            commit_sha=commit_sha,
            corpus_version=(
                corpus_version
                if corpus_version is not None
                else self._corpus_version
            ),
            workflow_id=self._correlation.workflow_id,
            run_id=self._correlation.run_id,
            payload=payload,
            agent_id=agent_id,
        )
