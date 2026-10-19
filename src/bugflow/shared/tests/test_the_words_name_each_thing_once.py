"""docs/words.md gives each word one line, which names where the word
is defined, and has a line for each thing the model names."""

import re

import pytest

from bugflow.shared.tests.model_section import REPOSITORY, things

WORDS = REPOSITORY / "docs" / "words.md"
LINE = re.compile(r"^- \*\*([^*]+?)\.\*\*(.*?)(?=^- \*\*|^#|\Z)", re.M | re.S)


def lines() -> list[tuple[str, str]]:
    """Each word of docs/words.md, in lower case, with the rest of its
    line."""
    return [
        (word.lower(), rest) for word, rest in LINE.findall(WORDS.read_text())
    ]


@pytest.mark.model(
    "The words documents", "bugflow's words document is docs/words.md."
)
@pytest.mark.model(
    "The words documents", "A words document gives each word one line."
)
def test_each_word_has_one_line() -> None:
    words = [word for word, _ in lines()]
    twice = sorted({word for word in words if words.count(word) > 1})
    assert words, "docs/words.md: no words"
    assert twice == [], f"docs/words.md: more than one line: {twice}"


@pytest.mark.model(
    "The words documents",
    "A word's line names the document, and the section where there is "
    "one, that defines the word.",
)
def test_each_line_names_a_document() -> None:
    unnamed = [word for word, rest in lines() if "](" not in rest]
    assert unnamed == [], f"docs/words.md: names no document: {unnamed}"


@pytest.mark.model(
    "Words coverage",
    "Each thing that bugflow's model names has a line in bugflow's words "
    "document.",
)
def test_each_thing_of_the_model_has_a_line() -> None:
    words = {word for word, _ in lines()}
    missing = [thing for thing in things() if thing not in words]
    assert missing == [], f"docs/words.md: no line for {missing}"
