"""Tests of reading a ``/dismiss`` command from a comment."""

import pytest

from bugflow.shared.domain.values.dismissal import Dismissal, parse_dismissal


def test_a_dismissal_names_the_policy_and_the_reason() -> None:
    assert parse_dismissal(
        "/dismiss ED-01 the sentence is evidence, not narration"
    ) == Dismissal(
        policy_id="ED-01", reason="the sentence is evidence, not narration"
    )


def test_only_the_first_line_is_the_command() -> None:
    assert parse_dismissal(
        "/dismiss SC-03 generated files\n\nMore context here."
    ) == Dismissal(policy_id="SC-03", reason="generated files")


def test_a_dismissal_is_rebuilt_from_its_journal_payload() -> None:
    assert Dismissal.from_payload(
        {"policy_id": "ED-01", "reason": "a quotation", "actor": "someone"}
    ) == Dismissal(policy_id="ED-01", reason="a quotation", actor="someone")
    assert (
        Dismissal.from_payload(
            {"policy_id": "ED-01", "reason": "a quotation"}
        ).actor
        is None
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Thanks!",
        "/dismiss ED-01",
        "/dismiss ed-01 a lower-case policy id",
        "please /dismiss ED-01 not at the start",
        "/dismissED-01 no space",
    ],
    ids=[
        "empty",
        "prose",
        "no reason",
        "lower case",
        "not first",
        "no space",
    ],
)
def test_anything_else_is_not_a_dismissal(text: str) -> None:
    assert parse_dismissal(text) is None
