"""Tests of reading an editor and its examples from their files."""

import pytest

from bugflow.method.domain.errors import PolicyDeploymentError
from bugflow.method.infrastructure.editor_files import (
    example_kind,
    parse_editor,
    parse_example,
)
from bugflow.method.tests.policy_files import BAD_EXAMPLE, EDITOR


def test_an_editor_file_is_a_model_class_and_instructions() -> None:
    editor = parse_editor("editor.md", EDITOR)
    assert editor.model_class == "medium"
    assert editor.instructions == (
        "You edit the draft of a review comment. Keep what the author "
        "must act\non, in the order it matters, and leave the rest out."
    )
    assert editor.examples == ()


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("model_class: medium\nEdit.\n", "no --- line after the header"),
        ("---\nEdit.\n", "no model_class line"),
        ("model_class: medium\nsummary: x\n---\nEdit.\n", "'summary' is not"),
        ("model_class: a\nmodel_class: b\n---\nEdit.\n", "two model_class"),
        ("medium\n---\nEdit.\n", "is not key: value"),
    ],
)
def test_a_malformed_editor_file_names_its_file(
    text: str, problem: str
) -> None:
    with pytest.raises(ValueError, match=rf"^editor\.md: .*{problem}"):
        parse_editor("editor.md", text)


def test_an_editor_with_no_instructions_is_refused() -> None:
    with pytest.raises(PolicyDeploymentError, match="has instructions"):
        parse_editor("editor.md", "model_class: small\n---\n\n")


def test_an_example_is_its_kind_its_why_and_the_comment() -> None:
    example = parse_example(
        "editor/examples/bad-01-every-finding.md", BAD_EXAMPLE
    )
    assert example.name == "bad-01-every-finding"
    assert example.kind == "bad"
    assert (
        example.why
        == "Every finding at the same weight, and the reason hedged."
    )
    assert example.text.startswith("Falls short of One reason")


@pytest.mark.parametrize(
    "name",
    ["good-01-brief.md", "bad-12-long-and-hedged.md", "good-007-x.md"],
)
def test_an_examples_name_says_what_it_shows(name: str) -> None:
    assert example_kind(f"editor/examples/{name}") == name.split("-")[0]


@pytest.mark.parametrize(
    "name",
    [
        "fine-01-x.md",
        "good-x.md",
        "good-01-Upper.md",
        "good-01-x.txt",
        "01-x.md",
    ],
)
def test_an_example_of_another_name_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match=r"is named good-NN-name\.md"):
        example_kind(f"editor/examples/{name}")


def test_an_example_with_no_comment_is_refused() -> None:
    with pytest.raises(PolicyDeploymentError, match="no comment"):
        parse_example("editor/examples/good-01-x.md", "why: Short.\n---\n\n")
