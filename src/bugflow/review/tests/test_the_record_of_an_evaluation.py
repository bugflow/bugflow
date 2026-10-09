"""Tests of ``review_record``: the record of an evaluation, built from
its journal entries."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.review.domain.models.record import review_record
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.correlation import Correlation

RUN = Correlation(workflow_id="pr-1", run_id="r1")
AT = datetime(2030, 9, 23, 12, tzinfo=UTC)


def entry(
    event_type: str,
    payload: dict[str, Any],
    *,
    agent_id: str | None = None,
    commit_sha: str | None = "abc1234",
    corpus_version: str | None = "corpus-1",
) -> JournalEntry:
    return JournalEntry(
        event_id=uuid4(),
        occurred_at=AT,
        event_type=event_type,
        forge="github",
        repo="orchard/pear-tree",
        pr_number=7,
        commit_sha=commit_sha,
        corpus_version=corpus_version,
        workflow_id=RUN.workflow_id,
        run_id=RUN.run_id,
        agent_id=agent_id,
        payload=payload,
    )


def finding(
    policy: str = "P-01",
    severity: str = "fail",
    subject: str = "pull request",
    message: str = "the description says nothing",
) -> dict[str, Any]:
    return {
        "policy_id": policy,
        "clause": "RULE-7",
        "subject": subject,
        "severity": severity,
        "message": message,
        "judged_by": "a-model",
        "agent_id": "prose",
        "corpus_version": "prose-2",
    }


def judged(
    policy: str = "P-01", exchange_id: str | None = "x1"
) -> JournalEntry:
    return entry(
        "judge.invoked",
        {
            "policy_id": policy,
            "status": "judged by a-model",
            "model": "a-model",
            "finding_count": 1,
            "unsupported": ["RULE-6: a quote nobody wrote"],
            "input_tokens": 900,
            "output_tokens": 30,
            "identity": {
                "model": "a-model",
                "fingerprint": "fp",
                "prompt_hash": "ph",
                "input_hash": "ih",
                "exchange_id": exchange_id,
            },
        },
        agent_id="prose",
    )


def test_the_record_names_the_evaluation_it_is_of() -> None:
    record = review_record(RUN, [entry("pr.observed", {})])
    assert (record.forge, record.repo, record.pr_number) == (
        "github",
        "orchard/pear-tree",
        7,
    )
    assert record.head_sha == "abc1234"
    assert record.correlation == RUN


def test_a_finding_carries_the_clause_it_rests_on() -> None:
    record = review_record(RUN, [entry("finding.raised", finding())])
    (one,) = record.findings
    assert (one.policy_id, one.clause, one.subject, one.severity) == (
        "P-01",
        "RULE-7",
        "pull request",
        "fail",
    )
    assert one.judged_by == "a-model"


def test_findings_are_ordered_worst_first() -> None:
    record = review_record(
        RUN,
        [
            entry("finding.raised", finding(severity="info", policy="P-02")),
            entry("finding.raised", finding(severity="fail")),
            entry("finding.raised", finding(severity="warn", policy="P-03")),
        ],
    )
    assert [f.severity for f in record.findings] == ["fail", "warn", "info"]


def test_what_this_evaluation_withdrew_is_kept_apart() -> None:
    record = review_record(
        RUN,
        [
            entry("finding.raised", finding()),
            entry("finding.resolved", finding(policy="P-02")),
        ],
    )
    assert [f.policy_id for f in record.findings] == ["P-01"]
    assert [f.policy_id for f in record.withdrawn] == ["P-02"]


def test_a_judgement_carries_the_model_that_answered_and_its_cost() -> None:
    record = review_record(RUN, [judged()])
    (one,) = record.policies
    assert (one.policy_id, one.model) == ("P-01", "a-model")
    assert (one.input_tokens, one.output_tokens) == (900, 30)
    assert one.unsupported == ("RULE-6: a quote nobody wrote",)


def test_a_judgement_carries_the_exchange_the_archive_holds() -> None:
    exchange = JudgeExchange(
        request={"prompt": "judge this"}, response={"violations": []}
    )
    record = review_record(RUN, [judged()], {"x1": exchange})
    (one,) = record.policies
    assert one.exchange_id == "x1"
    assert one.exchange == exchange


def test_every_judgement_is_kept_not_only_the_last() -> None:
    record = review_record(RUN, [judged("P-01", "x1"), judged("Q-01", "x2")])
    assert [p.policy_id for p in record.policies] == ["P-01", "Q-01"]
    assert [p.exchange_id for p in record.policies] == ["x1", "x2"]


def test_a_scan_records_a_run_with_no_model() -> None:
    record = review_record(
        RUN,
        [
            entry(
                "policy.checked",
                {
                    "policy_id": "P-04",
                    "clause": "RULE-21",
                    "finding_count": 2,
                },
                agent_id="prose",
            )
        ],
    )
    (one,) = record.policies
    assert (one.policy_id, one.model, one.finding_count) == ("P-04", None, 2)


def test_an_agents_run_names_where_its_transcript_is() -> None:
    record = review_record(
        RUN,
        [
            entry(
                "agent.dispatched",
                {
                    "agent_id": "safety",
                    "step": "dispatched",
                    "runner": "hosted",
                    "fingerprint": "fp",
                    "remote_id": "session-9",
                    "budget": {"usd": 2.0},
                    "withheld": [".env"],
                },
                agent_id="safety",
            ),
            entry(
                "agent.dispatched",
                {
                    "agent_id": "safety",
                    "step": "collected",
                    "outcome": "completed",
                    "runner": "hosted",
                    "fingerprint": "fp",
                    "cost": {"usd": 0.4},
                    "events": 31,
                    "detail": "",
                },
                agent_id="safety",
            ),
        ],
    )
    (one,) = record.agents
    assert (one.runner, one.remote_id, one.events) == (
        "hosted",
        "session-9",
        31,
    )
    assert one.outcome == "completed"
    assert one.cost == {"usd": 0.4} and one.budget == {"usd": 2.0}
    assert one.withheld == (".env",)


def test_an_agents_verdict_and_the_graders_note_are_both_kept() -> None:
    record = review_record(
        RUN,
        [
            entry(
                "agent.dispatched",
                {
                    "agent_id": "safety",
                    "step": "collected",
                    "outcome": "completed",
                },
                agent_id="safety",
            ),
            entry(
                "review.graded",
                {
                    "agent_id": "safety",
                    "status": "pass",
                    "detail": "answered both questions",
                },
                agent_id="safety",
            ),
        ],
    )
    (one,) = record.agents
    assert one.verdict == "pass"
    assert one.grader_note == "answered both questions"


def test_a_write_up_that_supported_no_verdict_leaves_none() -> None:
    record = review_record(
        RUN,
        [
            entry(
                "review.graded",
                {
                    "agent_id": "safety",
                    "status": None,
                    "detail": "the write-up answered nothing",
                },
                agent_id="safety",
            )
        ],
    )
    (one,) = record.agents
    assert one.verdict is None
    assert one.grader_note == "the write-up answered nothing"


def test_a_reused_verdict_says_which_evaluation_it_came_from() -> None:
    record = review_record(
        RUN,
        [
            entry(
                "agent.dispatched",
                {
                    "agent_id": "safety",
                    "step": "reused",
                    "fingerprint": "fp",
                    "reviewed_in": "r0",
                },
                agent_id="safety",
            )
        ],
    )
    (one,) = record.agents
    assert "r0" in one.reason


def test_what_was_published_carries_the_comment_id() -> None:
    record = review_record(
        RUN,
        [
            entry(
                "action.taken",
                {
                    "action": "outcome_label",
                    "performed": True,
                    "status": "published",
                    "label": "review:escalate",
                    "removed": [],
                },
            ),
            entry(
                "action.taken",
                {
                    "action": "review_comment",
                    "agent_id": "prose",
                    "performed": True,
                    "status": "published",
                    "comment_id": 4242,
                    "verdict": "2 findings",
                    "finding_count": 2,
                    "raised_count": 2,
                    "fixed_count": 0,
                    "dismissed_count": 0,
                },
            ),
        ],
    )
    assert record.label == "review:escalate"
    (one,) = record.said
    assert (one.agent_id, one.comment_id, one.raised) == (
        "prose",
        4242,
        2,
    )


def test_the_corpus_version_shown_is_the_servers_own() -> None:
    record = review_record(
        RUN,
        [
            entry(
                "finding.raised",
                finding(),
                agent_id="prose",
                corpus_version="prose-2",
            ),
            entry("pr.observed", {}, corpus_version="server-9"),
        ],
    )
    assert record.corpus_version == "server-9"


def test_an_evaluation_that_journalled_nothing_reads_as_empty() -> None:
    record = review_record(RUN, [])
    assert record.findings == () and record.policies == ()
    assert record.agents == () and record.said == ()
    assert record.correlation == RUN
