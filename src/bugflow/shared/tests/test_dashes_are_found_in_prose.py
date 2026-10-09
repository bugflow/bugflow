"""Tests of finding dashes used as punctuation."""

import pytest

from bugflow.shared.domain.values.typography import (
    em_dashes,
    has_em_dash,
    without_code,
)


@pytest.mark.parametrize("dash", ["\u2014", "\u2013", "\u2015"])
def test_each_of_the_three_dashes_is_found(dash: str) -> None:
    assert has_em_dash(f"The change is small {dash} one line.")


def test_a_hyphen_is_not_a_dash() -> None:
    assert not has_em_dash("A well-known, long-standing rule.")
    assert em_dashes("") == ()


def test_a_dash_in_code_is_not_reported() -> None:
    assert not has_em_dash("Run `git log \u2014 oneline` first.")
    assert not has_em_dash("Before\n```\na \u2014 b\n```\nafter.")


def test_blanking_code_keeps_the_length() -> None:
    text = "See `a \u2014 b` and ```c``` here."
    blank = without_code(text)
    assert len(blank) == len(text)
    assert "\u2014" not in blank
    assert blank.startswith("See ") and blank.endswith(" here.")


def test_a_dash_is_quoted_with_the_words_around_it() -> None:
    text = "The first part of it is long \u2014 and the second part follows."
    (quote,) = em_dashes(text)
    assert quote == "it is long \u2014 and the second part follows."


def test_white_space_in_a_quotation_is_made_single_spaces() -> None:
    (quote,) = em_dashes("one\n\ntwo \u2014\n   three")
    assert quote == "one two \u2014 three"


def test_two_dashes_in_one_sentence_give_two_quotations() -> None:
    text = (
        "The reviewer read the title \u2014 which was short \u2014 and then "
        "read the whole description to the end."
    )
    first, second = em_dashes(text)
    assert first != second
    assert first.startswith("d the title \u2014")
    assert second.startswith("h was short \u2014")
