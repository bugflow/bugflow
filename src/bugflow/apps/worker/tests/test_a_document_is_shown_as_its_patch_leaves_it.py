"""Tests of the evidence a policy reading documents is shown: each
changed document, as its patch leaves it, since a snapshot holds
patches and not files."""

from bugflow.apps.worker.litellm_judge import (
    DOCUMENT_BUDGET,
    EVIDENCE,
    render_document_evidence,
)
from bugflow.review.domain.models.submission import (
    Submission,
    SubmissionFile,
)

PATCH = """\
@@ -1,4 +1,4 @@
 #+TITLE: Tickets
 
-Each tracker is swept weekly.
+Each tracker is swept daily.
 The maintainer ruled this on 2025-03-02.
@@ -20,2 +20,3 @@
 * Tasks
+** TODO Sweep the trackers
 
"""


def changing(*files: SubmissionFile) -> Submission:
    return Submission(
        title="Sweep daily", body="", commits=(), files=tuple(files)
    )


def a_file(path: str, patch: str | None = PATCH) -> SubmissionFile:
    return SubmissionFile(path=path, additions=2, deletions=1, patch=patch)


def test_a_document_is_shown_as_the_lines_its_patch_leaves() -> None:
    """Kept and added lines in order, removed lines and hunk headers
    left out, and a mark where lines between hunks are not shown."""
    shown = render_document_evidence(changing(a_file("methods/tickets.org")))

    assert shown == (
        "<documents>\n"
        '<document path="methods/tickets.org" shown="the changed parts, '
        'after the change; [...] marks lines left out">\n'
        "#+TITLE: Tickets\n"
        "\n"
        "Each tracker is swept daily.\n"
        "The maintainer ruled this on 2025-03-02.\n"
        "[...]\n"
        "* Tasks\n"
        "** TODO Sweep the trackers\n"
        "\n"
        "</document>\n"
        "</documents>"
    )


def test_a_quote_must_come_from_the_lines_shown() -> None:
    _, quotable, _ = EVIDENCE["document/file"]
    text = quotable(changing(a_file("methods/tickets.org")))
    assert "Each tracker is swept daily." in text
    assert "swept weekly" not in text


def test_only_documents_are_shown() -> None:
    shown = render_document_evidence(
        changing(a_file("src/judge.py"), a_file("README.md"))
    )
    assert 'path="README.md"' in shown
    assert "judge.py" not in shown


def test_a_pull_request_that_changes_no_document_says_so() -> None:
    shown = render_document_evidence(changing(a_file("src/judge.py")))
    assert shown == (
        "<documents>\n"
        "<document>this pull request changes no document</document>\n"
        "</documents>"
    )


def test_a_patch_the_forge_left_out_is_said_to_be() -> None:
    shown = render_document_evidence(changing(a_file("big.org", None)))
    assert 'text="omitted by the forge"' in shown


def test_a_document_past_the_budget_is_omitted_and_named() -> None:
    long = "@@ -1,1 +1,1 @@\n+" + "x" * (DOCUMENT_BUDGET + 1) + "\n"
    shown = render_document_evidence(
        changing(a_file("small.org"), a_file("huge.org", long))
    )
    assert '<document path="small.org"' in shown
    assert (
        'path="huge.org" shown="the changed parts, after the change; ' in shown
    )
    assert 'text="omitted for size"' in shown
