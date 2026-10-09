"""Tests of reading a pull request reference from the forms people paste."""

import pytest

from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

EXPECTED = PullRequestRef(owner="someone", repo="a.project", number=8)


@pytest.mark.parametrize(
    "text",
    [
        "someone/a.project#8",
        "https://github.com/someone/a.project/pull/8",
        "https://github.com/someone/a.project/pull/8/",
        "https://forge.example.org/someone/a.project/pulls/8",
        "  someone/a.project#8\n",
    ],
)
def test_parses_short_form_and_forge_urls(text: str) -> None:
    assert PullRequestRef.parse(text) == EXPECTED


@pytest.mark.parametrize(
    "text",
    ["someone/a.project", "#8", "https://github.com/someone/8"],
)
def test_rejects_text_that_names_no_pull_request(text: str) -> None:
    with pytest.raises(ValueError, match="not a pull request reference"):
        PullRequestRef.parse(text)


def test_renders_in_short_form() -> None:
    assert str(EXPECTED) == "someone/a.project#8"
