"""Tests of the review ``Recorder``: the journal entries built for
findings."""

from datetime import UTC, datetime

from bugflow.review.domain.facts import (
    FINDING_RAISED,
    FINDING_RESOLVED,
    FINDING_REWRITTEN,
    FINDING_WITHHELD,
)
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.recorder import Recorder
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="orchard", repo="pear-tree", number=7)
RUN = Correlation(workflow_id="pr/7", run_id="run-2")
EARLIER = Correlation(workflow_id="pr/7", run_id="run-1")
AT = datetime(2030, 3, 1, tzinfo=UTC)


def finding(subject: str = "pull request") -> Finding:
    return Finding(
        policy_id="P-01",
        severity="warn",
        clause="RULE-1",
        subject=subject,
        message="a message",
        corpus_version="prose-3",
        agent_id="prose",
    )


def recorder() -> Recorder:
    return Recorder(REF, RUN, "server-1", AT)


def test_a_raised_finding_is_recorded_under_its_reviewer() -> None:
    (entry,) = recorder().findings("judge", [finding()])

    assert entry.event_type == FINDING_RAISED
    assert (entry.agent_id, entry.corpus_version) == ("prose", "prose-3")
    assert entry.payload["policy_id"] == "P-01"
    assert Finding.from_payload(entry.payload) == finding()
    assert (entry.repo, entry.pr_number) == ("orchard/pear-tree", 7)


def test_the_same_finding_from_two_steps_is_two_entries() -> None:
    (judged,) = recorder().findings("judge", [finding()])
    (checked,) = recorder().findings("check", [finding()])
    (again,) = recorder().findings("judge", [finding()])

    assert judged.event_id != checked.event_id
    assert judged.event_id == again.event_id


def test_a_resolved_finding_names_the_run_that_raised_it() -> None:
    (entry,) = recorder().resolutions(EARLIER, [finding()])

    assert entry.event_type == FINDING_RESOLVED
    assert entry.payload["raised_in_run_id"] == "run-1"
    assert entry.payload["raised_in_workflow_id"] == "pr/7"
    assert entry.run_id == "run-2"


def test_a_rewritten_finding_is_recorded_once_by_an_evaluation() -> None:
    (one,) = recorder().rewritten(EARLIER, [finding()])
    (two,) = recorder().rewritten(EARLIER, [finding()])

    assert one.event_type == FINDING_REWRITTEN
    assert one.event_id == two.event_id


def test_a_withheld_warning_is_recorded_with_the_share() -> None:
    (entry,) = recorder().withheld(0.25, [finding()])

    assert entry.event_type == FINDING_WITHHELD
    assert entry.payload["share"] == 0.25
    assert entry.agent_id == "prose"
