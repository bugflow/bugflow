"""Tests of the evidence a policy whose subject is document/glossary is
shown: each changed document, as document/file shows it, and then the
glossary files of the deployment in force, each in full."""

import pytest

from bugflow.apps.worker.litellm_judge import (
    judge_from_environment,
    render_document_evidence,
    render_glossary_evidence,
)
from bugflow.apps.worker.tests.policies import (
    GLOSSARY,
    KEY,
    POLICIES,
    deployed,
)
from bugflow.method.tests.policy_files import (
    MANIFEST,
    POLICY,
    READ,
    REFERENCES,
)
from bugflow.review.domain.models.submission import (
    Submission,
    SubmissionFile,
)

PATCH = "@@ -1,1 +1,2 @@\n Pollers.\n+A poller asks the forge.\n"

#: Two words documents, as a binding copies them in.
WORDS = {
    "glossary/bugflow/docs/words.md": "- **Poller.** A loop.\n",
    "glossary/clankos/docs/words.txt": "garden: a tree of Org files\n",
}

#: A policy of the example reviewer that reads the glossary.
GLOSSED = POLICY.replace("policy_id: P-01", "policy_id: P-02").replace(
    "evidence: description", "evidence: document/glossary"
)


def changing(*paths: str) -> Submission:
    return Submission(
        title="Name the poller",
        body="",
        commits=(),
        files=tuple(
            SubmissionFile(path=path, additions=1, deletions=0, patch=PATCH)
            for path in paths
        ),
    )


@pytest.mark.model(
    "Glossary",
    "A policy whose subject is document/glossary is shown the changed "
    "documents and then the glossary files.",
)
def test_the_changed_documents_are_shown_and_then_the_glossary() -> None:
    snapshot = changing("README.md")
    shown = render_glossary_evidence(snapshot, WORDS)

    assert shown == (
        render_document_evidence(snapshot) + "\n<glossary>\n"
        '<words path="glossary/bugflow/docs/words.md">\n'
        "- **Poller.** A loop.\n"
        "</words>\n"
        '<words path="glossary/clankos/docs/words.txt">\n'
        "garden: a tree of Org files\n"
        "</words>\n"
        "</glossary>"
    )


@pytest.mark.model(
    "Glossary",
    "A document of document/glossary is a .org or .md file, or a .txt "
    "file under docs/.",
)
def test_a_text_file_under_docs_is_a_document_and_one_elsewhere_is_not() -> (
    None
):
    shown = render_glossary_evidence(
        changing("docs/words.txt", "notes.txt", "a.org", "src/judge.py"),
        {},
    )
    assert '<document path="docs/words.txt"' in shown
    assert '<document path="a.org"' in shown
    assert "notes.txt" not in shown
    assert "judge.py" not in shown


def test_a_text_file_under_docs_is_not_a_document_of_document_file() -> None:
    shown = render_document_evidence(changing("docs/words.txt"))
    assert "docs/words.txt" not in shown


def test_a_quote_must_come_from_the_changed_documents() -> None:
    policy = POLICIES["P-07"]
    text = policy.quotable(changing("docs/words.txt", "notes.txt"))
    assert text == "Pollers.\nA poller asks the forge."
    assert all(words not in text for words in GLOSSARY.values())


def test_a_pull_request_that_changes_no_document_gives_nothing_to_quote() -> (
    None
):
    policy = POLICIES["P-07"]
    snapshot = changing("src/judge.py")
    assert policy.quotable(snapshot) == ""
    assert "this pull request changes no document" in policy.evidence(snapshot)


def test_a_deployment_with_no_glossary_is_said_to_hold_none() -> None:
    shown = render_glossary_evidence(changing("README.md"), {})
    assert shown.endswith(
        "<glossary>\nthis deployment holds no glossary file\n</glossary>"
    )


def judging(words: dict[str, str]) -> dict[str, str]:
    """A deployment whose reviewer judges the glossary policy, with
    these glossary files."""
    return (
        READ
        | {
            "prose/reviewer.md": MANIFEST.replace(
                "policies: P-01", "policies: P-01, P-02"
            ),
            f"{REFERENCES}/policies/P-02-glossary.md": GLOSSED,
        }
        | words
    )


def test_the_judge_shows_the_glossary_of_the_deployment_in_force() -> None:
    judge = judge_from_environment(
        {"LITELLM_MASTER_KEY": KEY}, deployed(judging(WORDS))
    )
    assert judge is not None
    assert judge.policies == ("P-01", "P-02")
    shown = judge.policy("P-02").evidence(changing("README.md"))
    assert '<words path="glossary/clankos/docs/words.txt">' in shown


def test_the_fingerprint_follows_the_glossary() -> None:
    """The glossary is part of what the model is shown, so another
    glossary is another judge."""
    environ = {"LITELLM_MASTER_KEY": KEY}
    before = judge_from_environment(environ, deployed(judging(WORDS)))
    after = judge_from_environment(
        environ,
        deployed(
            judging(
                WORDS | {"glossary/clankos/docs/words.txt": "garden: a tree\n"}
            )
        ),
    )
    assert before is not None and after is not None
    for one in (before, after):
        one._served = {}
    assert before.fingerprint != after.fingerprint
