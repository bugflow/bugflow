"""Tests of dispositions: which of them close a finding."""

from typing import get_args

from bugflow.shared.domain.values.disposition import (
    DEFAULT_DISPOSITION,
    DISPOSITIONS,
    ROUTED_TO_QUESTION,
    TERMINAL_DISPOSITIONS,
    Disposition,
    closes_finding,
    is_terminal,
)


def test_the_list_of_dispositions_matches_the_type() -> None:
    assert set(DISPOSITIONS) == set(get_args(Disposition))
    assert len(DISPOSITIONS) == len(get_args(Disposition))
    assert set(TERMINAL_DISPOSITIONS) <= set(DISPOSITIONS)
    assert ROUTED_TO_QUESTION in DISPOSITIONS


def test_a_record_with_no_disposition_is_read_as_done() -> None:
    assert DEFAULT_DISPOSITION == "accepted_done"
    assert is_terminal(DEFAULT_DISPOSITION)


def test_only_done_and_rejected_close_a_finding_by_themselves() -> None:
    assert is_terminal("accepted_done")
    assert is_terminal("rejected")
    assert not is_terminal("accepted_follow_up_pending")
    assert not is_terminal("deferred")
    assert not is_terminal("routed_to_question")


def test_done_and_rejected_close_whatever_the_questions_are() -> None:
    assert closes_finding("accepted_done", None, frozenset())
    assert closes_finding("rejected", "q-1", frozenset())


def test_pending_and_deferred_findings_stay_open() -> None:
    assert not closes_finding("accepted_follow_up_pending", None, frozenset())
    assert not closes_finding("deferred", None, frozenset({"q-1"}))


def test_a_routed_finding_closes_when_its_question_is_answered() -> None:
    assert closes_finding("routed_to_question", "q-1", frozenset({"q-1"}))
    assert not closes_finding("routed_to_question", "q-1", frozenset())
    assert not closes_finding("routed_to_question", "q-1", frozenset({"q-2"}))


def test_a_routed_finding_with_no_question_never_closes() -> None:
    assert not closes_finding("routed_to_question", None, frozenset({"q-1"}))
