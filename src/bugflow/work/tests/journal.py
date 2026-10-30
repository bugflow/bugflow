"""A journal for tests that can also answer the questions the work
context asks of it."""

from collections.abc import Mapping

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal
from bugflow.work.domain.facts import AGENT_DISPATCHED, JUDGE_INVOKED
from bugflow.work.domain.models.journal import (
    DispatchedRun,
)


class QueryableJournal(InMemoryJournal):
    """The in-memory journal, with the queries declared in
    ``work/domain/services/journal.py``.

    ``dispatch_tables`` names, by the kind of fact, the kinds of dispatch
    that ``dispatched_run`` searches, as it does for the Postgres
    adapter; this journal reads each from the payload it keeps."""

    def __init__(
        self,
        build: str | None = None,
        dispatch_tables: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(build)
        self._dispatch_facts = tuple(
            dispatch_tables
            if dispatch_tables is not None
            else {AGENT_DISPATCHED: "agent_dispatch"}
        )

    def events_for_pull_request(
        self, ref: PullRequestRef, event_type: str
    ) -> list[JournalEntry]:
        key = (ref.forge, f"{ref.owner}/{ref.repo}", ref.number)
        return sorted(
            (
                e
                for e in self.entries
                if e.event_type == event_type
                and (e.forge, e.repo, e.pr_number) == key
            ),
            key=lambda e: e.occurred_at,
        )

    def judged_runs(self, ref: PullRequestRef) -> set[Correlation]:
        return {
            Correlation(workflow_id=e.workflow_id, run_id=e.run_id)
            for e in self.events_for_pull_request(ref, JUDGE_INVOKED)
            if str(e.payload.get("status") or "").startswith("judged")
        }

    def dispatched_run(
        self, runner: str, remote_id: str
    ) -> DispatchedRun | None:
        for e in self.entries:
            if (
                e.event_type in self._dispatch_facts
                and e.payload.get("step") == "dispatched"
                and e.payload.get("runner") == runner
                and e.payload.get("remote_id") == remote_id
            ):
                return DispatchedRun(
                    correlation=Correlation(
                        workflow_id=e.workflow_id, run_id=e.run_id
                    ),
                    agent_id=str(e.payload.get("agent_id", "")),
                    forge=e.forge,
                    repo=e.repo,
                    pr_number=e.pr_number,
                    commit_sha=e.commit_sha,
                )
        return None
