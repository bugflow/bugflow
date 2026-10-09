"""A journal for tests that can also answer the questions the forge
context asks of it."""

from datetime import datetime

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal


class QueryableJournal(InMemoryJournal):
    """The in-memory journal, with the three queries declared in
    ``forge/domain/services/journal_history.py``."""

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

    def repositories_with(self, event_type: str) -> list[tuple[str, str]]:
        return sorted(
            {
                (e.forge, e.repo)
                for e in self.entries
                if e.event_type == event_type
            }
        )

    def received_since(self, ref: PullRequestRef, since: datetime) -> bool:
        return any(
            e.event_type == "delivery.received"
            and (e.forge, e.repo, e.pr_number)
            == (ref.forge, f"{ref.owner}/{ref.repo}", ref.number)
            and e.occurred_at >= since
            for e in self.entries
        )
