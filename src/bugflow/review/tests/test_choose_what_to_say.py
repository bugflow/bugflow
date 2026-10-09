"""Tests of ``ChooseWhatToSayUseCase``: the findings a comment carries
are chosen from what every evaluation of the pull request recorded."""

from datetime import timedelta

from bugflow.review.domain.facts import PR_OBSERVED
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.recorder import Recorder
from bugflow.review.dtos.choose_what_to_say import ChooseWhatToSayRequest
from bugflow.review.tests.doubles import NOW
from bugflow.review.tests.journal import QueryableJournal
from bugflow.review.usecases.choose_what_to_say import ChooseWhatToSayUseCase
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="orchard", repo="pear-tree", number=5)
OTHER = PullRequestRef(owner="orchard", repo="pear-tree", number=6)
OLD, HEAD = "a" * 40, "b" * 40


def finding(clause: str, severity: str = "warn") -> Finding:
    return Finding(
        policy_id="P-01",
        severity=severity,  # type: ignore[arg-type]
        clause=clause,
        subject="pull request",
        message=f"breaks {clause}",
    )


def evaluated(
    journal: QueryableJournal,
    run_id: str,
    head: str,
    *findings: Finding,
    ref: PullRequestRef = REF,
    minutes: int = 0,
) -> None:
    """Record what one evaluation leaves: the commit it read, and the
    findings it raised."""
    recorder = Recorder(
        ref,
        Correlation(workflow_id=f"pr/{ref.number}", run_id=run_id),
        "server-1",
        NOW + timedelta(minutes=minutes),
    )
    journal.append(
        [
            recorder.entry(PR_OBSERVED, head, {}, commit_sha=head),
            *recorder.findings("judged", findings),
        ]
    )


def chosen(journal: QueryableJournal) -> tuple[list[str], int]:
    response = ChooseWhatToSayUseCase(journal).execute(
        ChooseWhatToSayRequest(ref=REF, head_sha=HEAD)
    )
    return [f.clause for f in response.findings], response.considered


def test_one_evaluation_of_the_commit_says_all_it_found() -> None:
    journal = QueryableJournal()
    evaluated(journal, "run-1", HEAD, finding("RULE-2"), finding("RULE-1"))

    assert chosen(journal) == (["RULE-1", "RULE-2"], 2)


def test_a_finding_only_one_of_two_evaluations_raised_is_left_out() -> None:
    journal = QueryableJournal()
    evaluated(journal, "run-1", HEAD, finding("RULE-1"), finding("RULE-2"))
    evaluated(journal, "run-2", HEAD, finding("RULE-1"), minutes=1)

    assert chosen(journal) == (["RULE-1"], 2)


def test_findings_about_an_earlier_commit_are_ignored() -> None:
    journal = QueryableJournal()
    evaluated(journal, "run-1", OLD, finding("RULE-3"))
    evaluated(journal, "run-2", HEAD, finding("RULE-1"), minutes=1)

    assert chosen(journal) == (["RULE-1"], 1)


def test_findings_about_another_pull_request_are_ignored() -> None:
    journal = QueryableJournal()
    evaluated(journal, "run-1", HEAD, finding("RULE-3"), ref=OTHER)

    assert chosen(journal) == ([], 0)


def test_the_most_severe_finding_comes_first() -> None:
    journal = QueryableJournal()
    evaluated(
        journal,
        "run-1",
        HEAD,
        finding("RULE-1", "info"),
        finding("RULE-2", "fail"),
        finding("RULE-3", "warn"),
    )

    assert chosen(journal)[0] == ["RULE-2", "RULE-3", "RULE-1"]
