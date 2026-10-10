"""Tests of policies read from their files: the format, and what a
malformed file is told."""

from pathlib import Path

import pytest

from bugflow.method.infrastructure.policy_files import (
    load_policies,
    load_policy,
    policy_source,
    unwrap,
)

WHOLE = """\
policy_id: P-01
subject: description
summary: A policy for the tests
model_class: medium
evidence: description
quotable_name: title or description
graded: yes
quotes_code: no
clause: RULE-1 the first clause
clause: RULE-2 the second clause
---
One paragraph, wrapped
over two lines.

- A list item, wrapped
over two lines.
- A second item.
=== calibration
Met its bar, wrapped
over two lines.
"""


def written(tmp_path: Path, text: str, name: str = "P-01-policy.md") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def test_a_policy_file_is_a_header_instructions_and_a_calibration_note(
    tmp_path: Path,
) -> None:
    policy = load_policy(written(tmp_path, WHOLE))
    assert (policy.policy_id, policy.model_class) == ("P-01", "medium")
    assert policy.clauses == {
        "RULE-1": "the first clause",
        "RULE-2": "the second clause",
    }
    assert (policy.graded, policy.quotes_code) == (True, False)
    assert policy.calibration == "Met its bar, wrapped over two lines."


def test_wrapped_lines_are_joined_and_list_items_are_not(
    tmp_path: Path,
) -> None:
    """What the model is given is the paragraph, not the wrapping."""
    policy = load_policy(written(tmp_path, WHOLE))
    assert policy.instructions == (
        "One paragraph, wrapped over two lines.\n"
        "\n"
        "- A list item, wrapped over two lines.\n"
        "- A second item."
    )


def test_an_unwrapped_body_is_left_alone() -> None:
    assert unwrap("One line.\n\n- An item.") == "One line.\n\n- An item."


@pytest.mark.parametrize(
    ("before", "after", "message"),
    [
        ("\n---\n", "\n", "no --- line"),
        ("subject: description\n", "", "no subject line"),
        ("graded: yes", "graded: sort of", "not yes or no"),
        ("model_class: medium", "mood: medium", "not a policy"),
        ("clause: RULE-1 the first clause", "clause: RULE-1", "an id and a"),
        ("\n=== calibration\n", "\n", "no === calibration"),
        ("subject: description", "subject: a\nsubject: b", "two subject"),
        ("graded: yes", "graded: yes\nceiling: info", "ceiling is 'info'"),
        ("evidence: description", "evidence: telepathy", "not one of"),
    ],
)
def test_a_malformed_policy_names_its_file(
    tmp_path: Path, before: str, after: str, message: str
) -> None:
    path = written(tmp_path, WHOLE.replace(before, after))
    with pytest.raises(ValueError, match=f"P-01-policy.md: .*{message}"):
        load_policy(path)


def test_a_policy_with_no_clause_line_is_refused(tmp_path: Path) -> None:
    text = WHOLE.replace("clause: RULE-1 the first clause\n", "").replace(
        "clause: RULE-2 the second clause\n", ""
    )
    with pytest.raises(ValueError, match="no clause line"):
        load_policy(written(tmp_path, text))


def test_a_file_whose_name_does_not_open_with_its_id_is_refused(
    tmp_path: Path,
) -> None:
    """The filename is how a reader finds a policy, and how a URL names
    it."""
    path = written(tmp_path, WHOLE, name="something-else.md")
    with pytest.raises(ValueError, match="names P-01"):
        load_policy(path)


def test_two_files_may_not_claim_one_policy(tmp_path: Path) -> None:
    written(tmp_path, WHOLE)
    written(tmp_path, WHOLE, name="P-01-again.md")
    with pytest.raises(ValueError, match="P-01 twice"):
        load_policies(tmp_path)


def test_a_directory_with_no_policies_holds_none(tmp_path: Path) -> None:
    assert load_policies(tmp_path) == {}


def test_a_directory_that_is_not_there_holds_no_policy(tmp_path: Path) -> None:
    assert load_policies(tmp_path / "absent") == {}
    assert policy_source(tmp_path / "absent") == ""


def test_the_policy_source_is_every_file_down_to_its_calibration(
    tmp_path: Path,
) -> None:
    """What the model is asked, from every policy, and nothing below it.
    Hashing the calibration notes would make recording a measurement
    change the fingerprint the measurement was taken under."""
    written(tmp_path, WHOLE)
    asked, _, notes = WHOLE.partition("\n=== calibration\n")
    source = policy_source(tmp_path)
    assert source == asked
    assert notes not in source


def test_a_policy_may_fail_unless_its_ceiling_says_otherwise(
    tmp_path: Path,
) -> None:
    assert load_policy(written(tmp_path, WHOLE)).ceiling == "fail"
    capped = WHOLE.replace("graded: yes", "graded: yes\nceiling: warn")
    assert load_policy(written(tmp_path, capped)).ceiling == "warn"
