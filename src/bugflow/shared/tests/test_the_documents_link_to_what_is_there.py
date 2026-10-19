"""The documents under docs/ and the README link to files that are there.

A relative link in one of them names a file in the repository, and a
section a link in the words document names is a heading of the file
it names. Nothing is fetched: a link to a web address is not checked.
"""

import re
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[4]
DOCUMENTS = [
    REPOSITORY / "README.md",
    *sorted((REPOSITORY / "docs").glob("*.md")),
]
LINK = re.compile(r"\]\(([^)]+)\)")
QUOTED_SECTION = re.compile(r'\]\(([^)]+)\),\s*"([^"]+)"')


def relative_links(document: Path) -> list[str]:
    """The targets of the document's links that are not web addresses."""
    text = document.read_text()
    return [
        target
        for target in LINK.findall(text)
        if not target.startswith(("http://", "https://", "mailto:"))
    ]


def headings(document: Path) -> set[str]:
    """The headings of a Markdown document, without their marks."""
    return {
        line.lstrip("#").strip()
        for line in document.read_text().splitlines()
        if line.startswith("#")
    }


@pytest.mark.model(
    "The words documents",
    "The document and section that a word's line names exist.",
)
@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda d: d.name)
def test_each_relative_link_names_a_file(document: Path) -> None:
    missing = [
        target
        for target in relative_links(document)
        if not (document.parent / target.split("#")[0]).exists()
    ]
    assert missing == [], f"{document.name}: not there: {missing}"


@pytest.mark.model(
    "The words documents",
    "The document and section that a word's line names exist.",
)
def test_each_section_the_words_name_is_a_heading() -> None:
    words = REPOSITORY / "docs" / "words.md"
    wrong = []
    for target, quoted in QUOTED_SECTION.findall(words.read_text()):
        section = " ".join(quoted.split())
        if section not in headings(words.parent / target):
            wrong.append((target, section))
    assert wrong == [], f"docs/words.md: no such section: {wrong}"
