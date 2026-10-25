"""A journal entry as the review context reads it: the envelope, with
the fact its typed table holds (ADR 007).

The review journal's envelope carries no payload once its column has
gone, so a reader takes the fact from here and not from the payload.
An entry of a type this context has no table for, a forge's or a
stocktake's fact it also reads, has no fact and keeps its payload.
"""

from dataclasses import dataclass, fields

from bugflow.review.domain.models.journal_facts import (
    ReviewFact,
    fact_from_payload,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry


@dataclass(frozen=True, kw_only=True)
class ReviewEntry(JournalEntry):
    """A journal entry with the review fact its typed table holds, or
    None for a type this context has no table for."""

    fact: ReviewFact | None = None


def with_fact(entry: JournalEntry, fact: ReviewFact | None) -> ReviewEntry:
    """The entry as a review entry carrying ``fact``."""
    return ReviewEntry(
        **{f.name: getattr(entry, f.name) for f in fields(JournalEntry)},
        fact=fact,
    )


def from_payload(entry: JournalEntry) -> ReviewEntry:
    """The entry as a review entry, its fact read from the payload it was
    written with, as the in-memory journal reads it."""
    if isinstance(entry, ReviewEntry) and entry.fact is not None:
        return entry
    return with_fact(entry, fact_from_payload(entry.event_type, entry.payload))
