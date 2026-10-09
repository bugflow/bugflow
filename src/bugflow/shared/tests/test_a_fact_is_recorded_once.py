"""Tests that the same fact always gets the same id, and that the journal
keeps one entry for each id.
"""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from bugflow.shared.domain.models.journal_entry import (
    JournalEntry,
    event_id,
    fact_id,
)
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal

RUN = Correlation(workflow_id="a-workflow", run_id="a-run")


def entry(id_: UUID, payload: dict[str, object] | None = None) -> JournalEntry:
    return JournalEntry(
        event_id=id_,
        occurred_at=datetime(2026, 10, 1, tzinfo=UTC),
        event_type="archive.sealed",
        forge="a-forge",
        repo="some/one",
        pr_number=None,
        commit_sha=None,
        corpus_version=None,
        workflow_id=RUN.workflow_id,
        run_id=RUN.run_id,
        payload=payload or {},
    )


def test_the_way_ids_are_made_does_not_change() -> None:
    """Pins two ids. A journal keeps one entry for each id, so if the way
    ids are made changed, a fact recorded again would get a new id and be
    stored twice.
    """
    assert event_id(RUN, "archive.sealed", "a-key") == UUID(
        "1962fe15-e238-5f2c-946e-02c4ca25c4e7"
    )
    assert fact_id("archive-sealed", "a-ledger", "00000001-abc.json") == UUID(
        "e5f3d0d2-c36d-54fc-87cd-501e98516c9a"
    )


def test_different_parts_give_different_ids() -> None:
    assert fact_id("a", "b") != fact_id("a", "c")
    assert event_id(RUN, "archive.sealed", "one") != event_id(
        RUN, "archive.refused", "one"
    )


def test_an_entry_appended_twice_is_kept_once_and_stamped() -> None:
    journal = InMemoryJournal(build="a-build")
    one = entry(fact_id("one"))

    journal.append([one])
    journal.append([one, entry(fact_id("two"))])

    assert [e.event_id for e in journal.entries] == [
        fact_id("one"),
        fact_id("two"),
    ]
    assert {e.build for e in journal.entries} == {"a-build"}
    assert journal.has_event(fact_id("one"))
    assert not journal.has_event(fact_id("three"))


def test_a_payload_json_cannot_say_is_refused() -> None:
    journal = InMemoryJournal()
    with pytest.raises(TypeError):
        journal.append([entry(fact_id("one"), {"when": datetime.now(UTC)})])
    assert journal.entries == []
