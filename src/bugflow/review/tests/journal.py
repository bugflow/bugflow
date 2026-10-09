"""A journal for tests that can also answer the questions the review
context asks of it."""

from bugflow.review.domain.facts import ACTION_TAKEN
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal


class QueryableJournal(InMemoryJournal):
    """The in-memory journal, with the queries declared in
    ``review/domain/services/journal.py``."""

    def entries_for_run(self, correlation: Correlation) -> list[JournalEntry]:
        return [
            e
            for e in self.entries
            if (e.workflow_id, e.run_id)
            == (correlation.workflow_id, correlation.run_id)
        ]

    def latest_acted_run(
        self, ref: PullRequestRef, excluding: Correlation
    ) -> Correlation | None:
        for e in reversed(self.entries):
            run = Correlation(workflow_id=e.workflow_id, run_id=e.run_id)
            if (
                e.event_type == ACTION_TAKEN
                and (e.forge, e.repo, e.pr_number)
                == (ref.forge, f"{ref.owner}/{ref.repo}", ref.number)
                and run != excluding
            ):
                return run
        return None

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

    def events_for_repository(
        self, forge: str, repo: str, event_type: str
    ) -> list[JournalEntry]:
        return sorted(
            (
                e
                for e in self.entries
                if e.event_type == event_type
                and (e.forge, e.repo) == (forge, repo)
            ),
            key=lambda e: e.occurred_at,
        )
