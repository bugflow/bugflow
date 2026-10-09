"""Tests of ``worth_saying``: which findings a comment carries."""

from bugflow.review.domain.models.finding import Finding, Severity
from bugflow.review.domain.values.commentary import Seen, worth_saying

HEAD = "a" * 40
OLDER = "b" * 40


def finding(
    policy: str = "P-01",
    clause: str = "RULE-1",
    subject: str = "description",
    severity: Severity = "warn",
) -> Finding:
    return Finding(
        policy_id=policy,
        severity=severity,
        clause=clause,
        subject=subject,
        message=f"{clause} on {subject}",
    )


def seen(run: str, head: str, *findings: Finding) -> list[Seen]:
    return [Seen(run_id=run, read=head, finding=f) for f in findings]


def test_one_evaluation_says_what_it_found() -> None:
    said = worth_saying(seen("r1", HEAD, finding()), read=HEAD)
    assert [f.clause for f in said] == ["RULE-1"]


def test_a_finding_that_flickered_is_not_said() -> None:
    steady, flicker = finding(), finding(clause="RULE-27")
    history = seen("r1", HEAD, steady, flicker) + seen("r2", HEAD, steady)
    said = worth_saying(history, read=HEAD)
    assert [f.clause for f in said] == ["RULE-1"]


def test_a_finding_the_last_evaluation_did_not_raise_is_not_said() -> None:
    gone = finding(clause="RULE-27")
    history = seen("r1", HEAD, gone) + seen("r2", HEAD, finding())
    assert [f.clause for f in worth_saying(history, read=HEAD)] == []


def test_evaluations_of_an_earlier_head_are_not_counted() -> None:
    steady = finding()
    history = seen("r0", OLDER, steady) + seen("r1", HEAD, steady)
    assert [f.clause for f in worth_saying(history, read=HEAD)] == ["RULE-1"]


def test_what_is_said_is_ordered_by_what_it_costs_a_reader() -> None:
    fail = finding(policy="Q-01", clause="RULE-90", severity="fail")
    warn = finding(policy="P-01", clause="RULE-1", severity="warn")
    info = finding(policy="P-02", clause="RULE-2", severity="info")
    said = worth_saying(seen("r1", HEAD, info, warn, fail), read=HEAD)
    assert [f.severity for f in said] == ["fail", "warn", "info"]


def test_one_passage_broken_twice_is_said_twice() -> None:
    one = finding(clause="RULE-1")
    two = finding(clause="RULE-19")
    said = worth_saying(seen("r1", HEAD, one, two), read=HEAD)
    assert len(said) == 2


def test_nothing_found_is_nothing_said() -> None:
    assert worth_saying([], read=HEAD) == ()


def test_a_finding_that_arrived_late_at_one_text_is_not_said() -> None:
    late = finding(clause="RULE-27")
    history = seen("r1", HEAD, finding()) + seen("r2", HEAD, finding(), late)
    assert [f.clause for f in worth_saying(history, read=HEAD)] == ["RULE-1"]
