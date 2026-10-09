"""Tests of the words a finding quotes, and whether a pull request
still contains them."""

from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.submission import (
    Submission,
    SubmissionCommit,
    SubmissionFile,
)
from bugflow.review.domain.values.passage import (
    passages,
    quoted,
    stands,
    unmarked,
)


def finding(message: str, subject: str = "description") -> Finding:
    return Finding(
        policy_id="P-01",
        severity="warn",
        clause="RULE-6",
        subject=subject,
        message=message,
    )


def test_the_quote_is_what_the_message_opens_with() -> None:
    assert (
        quoted(finding('"a seamless, robust poller": marketing register.'))
        == "a seamless, robust poller"
    )


def test_a_quote_holding_the_separator_is_read_by_its_subject() -> None:
    message = '"says "done": it is not": a claim, not a fact.'
    whole = finding(message, subject='description "says "done": it is not"')
    assert quoted(whole) == 'says "done": it is not'
    assert quoted(finding(message)) == 'says "done'


def test_a_finding_that_quotes_nothing_has_no_passage() -> None:
    assert quoted(finding("diff of 900 lines")) == ""
    assert stands(finding("diff of 900 lines"), "anything") is None


def test_the_passages_are_everything_a_policy_may_quote() -> None:
    text = passages(
        Submission(
            title="Add   a poller",
            body="It **polls**.",
            commits=(
                SubmissionCommit(sha="a" * 40, message="Add a poller\n"),
            ),
            files=(
                SubmissionFile(
                    path="src/poller.py", additions=1, deletions=0, patch=None
                ),
            ),
        )
    )
    assert text == "Add a poller It polls. Add a poller src/poller.py"


def test_markup_and_wrapping_do_not_hide_a_passage() -> None:
    text = unmarked("a *seamless*\npoller")
    assert stands(finding('"a seamless poller": marketing register.'), text)
    assert (
        stands(finding('"a robust poller": marketing register.'), text)
        is False
    )
