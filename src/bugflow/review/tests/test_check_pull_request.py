"""Tests of ``CheckPullRequestUseCase``: the em dash check, under the
policy id and clause the request gives."""

from bugflow.review.domain.facts import FINDING_RAISED, POLICY_CHECKED
from bugflow.review.domain.models.submission import Submission
from bugflow.review.domain.values.checked_policy import (
    CHECKED_COST_USD,
    CHECKS,
    EM_DASH_CHECK,
)
from bugflow.review.dtos.check_pull_request import (
    CheckPullRequestRequest,
    CheckPullRequestResponse,
)
from bugflow.review.tests.doubles import FixedClock, InMemorySubmissions
from bugflow.review.tests.journal import QueryableJournal
from bugflow.review.usecases.check_pull_request import CheckPullRequestUseCase
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="orchard", repo="pear-tree", number=5)
RUN = Correlation(workflow_id="pr/5", run_id="run-1")
DASH = "\u2014"


def checked(
    title: str, body: str, agent_id: str = "prose"
) -> tuple[CheckPullRequestResponse, QueryableJournal]:
    journal, submissions = QueryableJournal(), InMemorySubmissions()
    snapshot = submissions.put(
        REF, Submission(title=title, body=body, commits=(), files=())
    )
    response = CheckPullRequestUseCase(
        submissions, journal, FixedClock()
    ).execute(
        CheckPullRequestRequest(
            snapshot=snapshot,
            policy_id="P-04",
            clause="RULE-21",
            corpus_version="prose-3",
            agent_id=agent_id,
            correlation=RUN,
        )
    )
    return response, journal


def test_the_server_names_the_check_and_no_policy() -> None:
    assert CHECKS == (EM_DASH_CHECK,)
    assert EM_DASH_CHECK == "em-dash"


def test_a_dash_in_the_description_is_a_warning_under_the_given_ids() -> None:
    response, _ = checked("Add a poller", f"It polls {DASH} every minute.")

    (finding,) = response.findings
    assert (finding.policy_id, finding.clause) == ("P-04", "RULE-21")
    assert finding.severity == "warn"
    assert finding.subject == f'description "er It polls {DASH} every minute."'
    assert finding.message.startswith(f'"er It polls {DASH} every minute.": ')
    assert (finding.agent_id, finding.corpus_version) == ("prose", "prose-3")
    assert finding.judged_by is None and finding.judge is None
    assert response.answered == ("P-04",)
    assert response.status == "checked: 1 em dashes"


def test_the_title_is_checked_too_and_each_dash_is_a_finding() -> None:
    response, _ = checked(
        f"Add a poller {DASH} at last",
        f"One {DASH} two.\n\nThree {DASH} four.",
    )

    assert len(response.findings) == 3
    assert len({f.subject for f in response.findings}) == 3


def test_a_long_quotation_is_shortened_in_the_subject() -> None:
    after = "word " * 20
    response, _ = checked("Add a poller", f"Start {DASH} {after}")

    (finding,) = response.findings
    assert finding.subject.endswith('..."')
    assert len(finding.subject) < len(finding.message)


def test_a_dash_in_code_is_not_a_finding() -> None:
    response, _ = checked("Add a poller", f"Run `poll {DASH} now` first.")

    assert response.findings == ()
    assert response.status == "checked: 0 em dashes"


def test_a_run_that_finds_nothing_is_still_recorded_with_its_cost() -> None:
    response, journal = checked("Add a poller", "It polls.")

    assert response.answered == ("P-04",)
    (entry,) = journal.entries
    assert entry.event_type == POLICY_CHECKED
    assert entry.payload == {
        "policy_id": "P-04",
        "clause": "RULE-21",
        "finding_count": 0,
        "cost": {"usd": CHECKED_COST_USD},
    }
    assert CHECKED_COST_USD > 0
    assert (entry.agent_id, entry.corpus_version) == ("prose", "prose-3")


def test_the_findings_are_recorded_beside_the_run() -> None:
    _, journal = checked("Add a poller", f"It polls {DASH} every minute.")

    assert [e.event_type for e in journal.entries] == [
        POLICY_CHECKED,
        FINDING_RAISED,
    ]
    assert journal.entries[0].payload["finding_count"] == 1


def test_with_no_reviewer_the_record_names_no_agent() -> None:
    response, journal = checked(
        "Add a poller", f"It polls {DASH} always.", agent_id=""
    )

    assert response.findings[0].agent_id is None
    assert journal.entries[0].agent_id is None
