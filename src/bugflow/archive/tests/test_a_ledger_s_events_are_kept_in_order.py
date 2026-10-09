"""A kept ledger's events come back in order, each kept once."""

import pytest

from bugflow.archive.domain.models.kept_event import KeptEvent
from bugflow.archive.domain.repositories.kept_events import EventTakenError
from bugflow.archive.infrastructure.in_memory_kept_events import (
    InMemoryKeptEvents,
)

LEDGER = "0f1e2d3c-4b5a-4968-8778-a6b5c4d3e2f1"
OTHER = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


def event(number: int, ledger: str = LEDGER, data: bytes = b"{}") -> KeptEvent:
    return KeptEvent(
        ledger_id=ledger,
        number=number,
        name=f"{number:08}-name.json",
        data=data,
        claims={"head": "abc"},
        caller="someone",
    )


def test_a_ledger_s_events_come_back_in_order_and_no_other_s() -> None:
    kept = InMemoryKeptEvents()
    for added in (event(2), event(1), event(1, OTHER)):
        kept.add(added)

    assert kept.of_ledger(LEDGER) == [event(1), event(2)]
    assert kept.of_ledger("3c4d5e6f-7a8b-4c9d-8e0f-1a2b3c4d5e6f") == []


def test_an_event_is_kept_once_and_never_replaced() -> None:
    kept = InMemoryKeptEvents()
    kept.add(event(1, data=b"first"))

    with pytest.raises(EventTakenError):
        kept.add(event(1, data=b"second"))

    assert kept.of_ledger(LEDGER) == [event(1, data=b"first")]


def test_an_event_s_number_counts_from_one() -> None:
    with pytest.raises(ValueError):
        event(0)
