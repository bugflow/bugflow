"""Tests of the text of the comments a reviewer posts."""

from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.grading import author_note
from bugflow.review.domain.models.review import ReviewNote
from bugflow.review.domain.values.review_comments import (
    agent_comment,
    clause_page,
    clean_comment,
    findings_comment,
    passage_of,
    reviewer_name,
)

MARKER = "<!-- m -->"
HEAD = "c" * 40


def said(message: str, subject: str = 'description "x"') -> Finding:
    return Finding(
        policy_id="P-01",
        severity="warn",
        clause="RULE-19",
        subject=subject,
        message=message,
    )


def test_a_reviewer_names_itself_in_words() -> None:
    assert reviewer_name("safety") == "Safety review"


def test_a_passage_is_where_it_is_what_it_says_and_what_is_wrong() -> None:
    assert passage_of(
        said('"Some of it was wrong:": Narrates the discovery.')
    ) == ("description", "Some of it was wrong:", "Narrates the discovery.")
    assert passage_of(said("No quote here.", subject="0123456")) == (
        "0123456",
        "",
        "No quote here.",
    )


def test_a_passage_in_a_commit_says_which() -> None:
    body = findings_comment(
        MARKER,
        "prose",
        [said('"Added it": Past tense.', subject='commit 1a2b3c4 "Added it"')],
        [],
        [said('"Added it": Past tense.')],
        clauses=CLAUSES,
    )
    assert (
        "<details><summary>Falls short of <b>No narration</b> in commit "
        "1a2b3c4.</summary>\n\n> Added it\n\nPast tense.\n\n</details>"
    ) in body


def test_a_passage_with_no_clause_to_name_is_graded_alone() -> None:
    finding = said("Past tense.", subject="1a2b3c4")
    body = findings_comment(MARKER, "prose", [finding], [], [finding])
    assert (
        "<summary><b>Warning</b> in commit 1a2b3c4.</summary>\n\nPast tense."
        in body
    )
    assert "RULE-19" not in body


def test_the_first_line_counts_what_stands_and_what_is_new_follows() -> None:
    new = said('"a": New.')
    old = said('"b": Old.', subject='description "b"')
    body = findings_comment(MARKER, "prose", [new], [], [new, old])
    assert "**Prose review:** 2 warnings." in body
    assert "One more, raised earlier, still stands." in body
    assert "> b" not in body


def test_what_was_fixed_is_a_count_with_its_passages_folded() -> None:
    gone = said('"Some of it was wrong:": Narrates.')
    body = findings_comment(MARKER, "prose", [], [gone, gone], [])
    assert "**Prose review: nothing to raise.**" in body
    assert (
        "<details><summary>1 passage fixed since the last review</summary>"
    ) in body
    assert '- "Some of it was wrong:"' in body


def test_a_clean_first_word_says_what_was_read_and_folds_for_what() -> None:
    body = clean_comment(
        MARKER, "prose", "The description was read.", ["One reason."]
    )
    assert body.startswith(
        f"{MARKER}\n\n**Prose review: nothing to raise.** "
        "The description was read."
    )
    assert "<details><summary>What it was read for</summary>" in body
    assert "- One reason\n" in body


def test_a_note_of_one_paragraph_follows_the_verdict() -> None:
    note = ReviewNote(agent_id="safety", head_sha=HEAD, note="It holds.")
    assert agent_comment(MARKER, "pass", note) == (
        f"{MARKER}\n\n**Safety review: nothing to raise.** It holds.\n"
    )


def test_a_note_with_quoted_lines_starts_below_the_verdict() -> None:
    note = ReviewNote(
        agent_id="safety",
        head_sha=HEAD,
        note="auth.py:12 lets anyone in:\n\n    return True",
    )
    body = agent_comment(MARKER, "fail", note)
    assert "**Safety review: a problem to fix.**\n\nauth.py:12" in body


def test_the_note_is_what_follows_its_heading() -> None:
    write_up = "Working.\n\n## For the author\n\nIt holds, because.\n"
    assert author_note(write_up) == "It holds, because."
    assert author_note("Working, and no note.") == ""


CLAUSES = {
    "RULE-19": "**RULE-19. No narration.** Say what the change does.",
    "RULE-2": "**RULE-2.** Keep it short.",
}


def test_each_finding_is_folded_under_the_clause_it_breaks() -> None:
    one = said('"First we tried": Narrates.', subject='description "First"')
    two = said('"Then we found": Narrates.', subject='description "Then"')
    body = findings_comment(
        MARKER, "prose", [one, two], [], [one, two], clauses=CLAUSES
    )
    assert "Say what the change does" not in body
    assert "RULE-19" not in body
    assert (
        body.count(
            "<summary>Falls short of <b>No narration</b> in the description."
            "</summary>"
        )
        == 2
    )
    assert "> First we tried\n\nNarrates.\n\n</details>" in body
    assert "> Then we found\n\nNarrates.\n\n</details>" in body


def test_a_clause_with_no_name_takes_the_policys_summary() -> None:
    finding = Finding(
        policy_id="P-02",
        severity="fail",
        clause="RULE-2",
        subject="pull request",
        message="the description runs to four screens.",
    )
    body = findings_comment(
        MARKER,
        "prose",
        [finding],
        [],
        [finding],
        summaries={"P-02": "A useful description."},
        clauses=CLAUSES,
    )
    assert "**Prose review:** 1 failure." in body
    assert "Keep it short" not in body
    assert (
        "<summary>Violates <b>A useful description</b> in the pull request."
        "</summary>\n\nThe description runs to four screens." in body
    )


def test_a_checked_passage_loses_its_cut_off_first_and_last_words() -> None:
    checked = said('"ller It polls now and then aga": A dash stands here.')
    judged = Finding(
        policy_id="P-01",
        severity="warn",
        clause="RULE-19",
        subject='description "x"',
        message='"ller It polls now and then aga": Narrates.',
        judged_by="a-model",
    )
    assert "> …It polls now and then…\n" in findings_comment(
        MARKER, "prose", [checked], [], [checked]
    )
    assert "> ller It polls now and then aga\n" in findings_comment(
        MARKER, "prose", [judged], [], [judged]
    )


SITE = "https://example.github.io/prose/"


def test_a_finding_quotes_the_passage_then_links_the_clause_it_breaks() -> (
    None
):
    finding = Finding(
        policy_id="P-01",
        severity="fail",
        clause="RULE-19",
        subject='description "First we tried"',
        message='"First we tried": Narrates the discovery.',
        judged_by="a-model",
    )
    body = findings_comment(
        MARKER, "prose", [finding], [], [finding], clauses=CLAUSES, site=SITE
    )
    assert (
        '<summary>Violates <a href="https://example.github.io/prose/doctrine/'
        '#RULE-19">No narration</a> in the description.</summary>\n\n'
        "> First we tried\n\nNarrates the discovery.\n"
    ) in body


def test_the_clauses_page_is_the_doctrines_anchored_by_its_id() -> None:
    assert (
        clause_page("https://example.github.io/prose", "RULE-19")
        == "https://example.github.io/prose/doctrine/#RULE-19"
    )
    assert clause_page("", "RULE-19") == ""


def test_a_passage_of_several_lines_is_quoted_whole() -> None:
    finding = said('"First line\nsecond line": Two lines.')
    body = findings_comment(MARKER, "prose", [finding], [], [finding])
    assert "> First line\n> second line\n\nTwo lines." in body


def test_the_severity_is_the_verb() -> None:
    def graded(severity: str) -> Finding:
        return Finding(
            policy_id="P-01",
            severity=severity,  # type: ignore[arg-type]
            clause="RULE-19",
            subject="pull request",
            message="So.",
        )

    for severity, verb in (
        ("fail", "Violates"),
        ("warn", "Falls short of"),
        ("info", "Bears on"),
    ):
        finding = graded(severity)
        body = findings_comment(
            MARKER, "prose", [finding], [], [finding], clauses=CLAUSES
        )
        assert f"{verb} <b>No narration</b> in the pull request." in body


def test_a_passage_in_the_title_says_so() -> None:
    finding = said('"Fixes stuff": Vague.', subject='title "Fixes stuff"')
    body = findings_comment(
        MARKER, "prose", [finding], [], [finding], clauses=CLAUSES
    )
    assert "Falls short of <b>No narration</b> in the title." in body
    assert "> Fixes stuff\n\nVague." in body


def test_a_review_that_changed_while_the_pull_request_did_not_says_so() -> (
    None
):
    finding = said('"a": New.')
    body = findings_comment(
        MARKER, "prose", [finding], [], [finding], rejudged=True
    )
    assert "The pull request has not changed since the last review" in body


def test_with_no_note_the_write_up_is_folded_under_the_verdict() -> None:
    note = ReviewNote(
        agent_id="safety", head_sha=HEAD, write_up="I read every file."
    )
    body = agent_comment(MARKER, "warn", note)
    assert "**Safety review: something to consider.**" in body
    assert "<details><summary>The review</summary>" in body
    assert "I read every file." in body
