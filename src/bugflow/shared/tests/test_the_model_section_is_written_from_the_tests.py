"""The model section of docs/architecture.md lists the requirements of
docs/model.toml, and each requirement is held by a marked test or names
what holds it."""

from bugflow.shared.tests.model_section import (
    ARCHITECTURE,
    marks,
    requirements,
    written,
)


def test_each_mark_names_a_requirement() -> None:
    known = {(r["group"], r["text"]) for r in requirements()}
    unknown = [
        (group, text, path.name)
        for group, text, path in marks()
        if (group, text) not in known
    ]
    assert unknown == [], f"not in docs/model.toml: {unknown}"


def test_each_requirement_is_tested_or_names_what_holds_it() -> None:
    marked = {(group, text) for group, text, _ in marks()}
    unheld = [
        r["text"]
        for r in requirements()
        if "held_by" not in r and (r["group"], r["text"]) not in marked
    ]
    assert unheld == [], f"no test holds: {unheld}"


def test_each_requirement_is_a_sentence() -> None:
    fragments = [
        r["text"] for r in requirements() if not r["text"].endswith(".")
    ]
    assert fragments == [], f"not a sentence: {fragments}"


def test_the_section_is_current() -> None:
    document = ARCHITECTURE.read_text()
    assert document == written(document), (
        "docs/architecture.md: run python -m "
        "bugflow.shared.tests.model_section"
    )
