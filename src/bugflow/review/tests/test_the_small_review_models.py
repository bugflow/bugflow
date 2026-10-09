"""Tests of the smaller parts of the review domain: the label, a
doctrine's clauses, corpus versions, failing statuses, withheld
warnings, a write-up's note and its key."""

from bugflow.review.domain.errors import (
    GraderUnavailableError,
    JudgeTemporarilyUnavailableError,
    JudgeUnavailableError,
)
from bugflow.review.domain.models.corpus import Corpus
from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.enforcement import Enforcement, fails
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.grading import author_note
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.review.domain.models.review import ReviewVerdict, project
from bugflow.review.domain.models.submission import (
    Submission,
    SubmissionCommit,
)
from bugflow.review.domain.models.write_up import WriteUp
from bugflow.review.domain.values.withholding import drawn
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

HEAD = "a" * 40
DOCTRINE = DoctrineText(
    text=(
        "# Rules\n\n"
        "**RULE-1.** Say why the change was made.\n"
        "Second line of the same clause.\n\n"
        "**RULE-2. Short titles.** Keep a title under fifty characters.\n"
    )
)


def verdict(agent_id: str, status: str, head: str = HEAD) -> ReviewVerdict:
    return ReviewVerdict(agent_id=agent_id, head_sha=head, status=status)  # type: ignore[arg-type]


def test_no_governing_reviewer_is_not_a_pass() -> None:
    assert project(HEAD, [], [verdict("prose", "pass")]) == "review:wip"


def test_every_governing_reviewer_passing_is_a_pass() -> None:
    verdicts = [verdict("prose", "pass"), verdict("safety", "warn")]
    assert project(HEAD, ["prose", "safety"], verdicts) == "review:pass"


def test_a_missing_verdict_keeps_the_label_at_wip() -> None:
    assert (
        project(HEAD, ["prose", "safety"], [verdict("prose", "pass")])
        == "review:wip"
    )


def test_a_fail_escalates_even_while_another_verdict_is_missing() -> None:
    assert (
        project(HEAD, ["prose", "safety"], [verdict("prose", "fail")])
        == "review:escalate"
    )


def test_other_commits_and_other_reviewers_are_ignored() -> None:
    verdicts = [
        verdict("prose", "fail", head="b" * 40),
        verdict("visitor", "fail"),
        verdict("prose", "pass"),
    ]
    assert project(HEAD, ["prose"], verdicts) == "review:pass"


def test_a_clause_is_found_by_its_id() -> None:
    assert DOCTRINE.clause("RULE-1") == (
        "**RULE-1.** Say why the change was made.\n"
        "Second line of the same clause."
    )
    assert DOCTRINE.clause("RULE-2") == (
        "**RULE-2. Short titles.** Keep a title under fifty characters."
    )
    assert DOCTRINE.clause("RULE-3") is None


def test_a_doctrines_version_follows_its_text() -> None:
    assert len(DOCTRINE.version) == 12
    assert DoctrineText(text="other").version != DOCTRINE.version


def test_a_corpus_version_follows_the_doctrine_and_the_judge() -> None:
    one = Corpus(doctrine=DOCTRINE, judge="j1")
    assert one.version == Corpus(doctrine=DOCTRINE, judge="j1").version
    assert one.version != Corpus(doctrine=DOCTRINE, judge="j2").version
    assert one.version != Corpus(doctrine=DOCTRINE, judge=None).version


def test_an_installed_reviewer_has_a_version_of_its_own() -> None:
    corpus = Corpus(doctrine=DOCTRINE, judge="j1", installed={"prose": "p7"})
    assert corpus.version_for("prose") == "p7"
    assert corpus.version_for("safety") == corpus.version


def test_which_verdicts_fail_a_commit_status() -> None:
    advice = Enforcement(publishes=True, fails_at=None)
    on_fail = Enforcement(publishes=True, fails_at="fail")
    on_warn = Enforcement(publishes=True, fails_at="warn")
    assert not fails(advice, "fail")
    assert fails(on_fail, "fail") and not fails(on_fail, "warn")
    assert fails(on_warn, "warn") and fails(on_warn, "fail")
    assert not fails(on_warn, "pass") and not fails(on_warn, None)


def warning(subject: str, severity: str = "warn") -> Finding:
    return Finding(
        policy_id="P-01",
        severity=severity,  # type: ignore[arg-type]
        clause="RULE-1",
        subject=subject,
        message="a message",
    )


REF = PullRequestRef(owner="orchard", repo="pear-tree", number=7)


def test_a_share_of_warnings_is_kept_out_and_always_the_same_ones() -> None:
    warnings = [warning(f"commit {n}") for n in range(400)]
    kept_out = [w for w in warnings if drawn(REF, w, 0.25)]
    assert 60 < len(kept_out) < 140
    assert kept_out == [w for w in warnings if drawn(REF, w, 0.25)]


def test_nothing_is_kept_out_at_a_share_of_zero_and_all_at_one() -> None:
    warnings = [warning(f"commit {n}") for n in range(50)]
    assert not any(drawn(REF, w, 0.0) for w in warnings)
    assert all(drawn(REF, w, 1.0) for w in warnings)


def test_only_a_warning_is_ever_kept_out() -> None:
    assert not drawn(REF, warning("commit 1", "fail"), 1.0)
    assert not drawn(REF, warning("commit 1", "info"), 1.0)


def test_the_note_to_the_author_follows_its_heading() -> None:
    write_up = "I read the diff.\n\n## For the author:\n\nRename `x`.\n"
    assert author_note(write_up) == "Rename `x`."
    assert author_note("I read the diff.") == ""


def test_a_write_up_is_stored_under_its_run_and_agent() -> None:
    run = Correlation(workflow_id="pr/7", run_id="run-1")
    write_up = WriteUp(correlation=run, agent_id="safety", text=" \n ")
    assert write_up.write_up_id == "pr/7/run-1/safety"
    assert not write_up.is_prose


def test_an_exchange_and_a_submission_are_identified_by_content() -> None:
    one = JudgeExchange(request={"a": 1}, response={"b": 2})
    assert one.exchange_id == (
        JudgeExchange(request={"a": 1}, response={"b": 2}).exchange_id
    )
    assert one.exchange_id != (
        JudgeExchange(request={"a": 1}, response={"b": 3}).exchange_id
    )
    submission = Submission(
        title="Add a poller",
        body="It polls.",
        commits=(SubmissionCommit(sha="c1", message="Add a poller"),),
        files=(),
    )
    assert len(submission.content_id) == 64


def test_an_unavailable_judge_or_grader_carries_its_calls() -> None:
    assert JudgeUnavailableError("no").calls == ()
    later = JudgeTemporarilyUnavailableError("busy")
    assert later.retry_after is None and later.calls == ()
    assert isinstance(later, JudgeUnavailableError)
    assert GraderUnavailableError("no").calls == ()
