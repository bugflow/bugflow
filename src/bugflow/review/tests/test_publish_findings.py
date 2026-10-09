"""Tests of ``PublishFindingsUseCase``: each reviewer's comment and
commit status, and the one label."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from bugflow.review.domain.errors import (
    PublicationRejectedError,
    SubmissionNotFoundError,
)
from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.enforcement import Enforcement
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.recorder import Recorder
from bugflow.review.domain.models.review import ReviewNote, ReviewVerdict
from bugflow.review.domain.models.submission import (
    Submission,
    SubmissionCommit,
    SubmissionFile,
    SubmissionRef,
)
from bugflow.review.domain.services.publication import CommitState
from bugflow.review.dtos.publish_findings import PublishFindingsRequest
from bugflow.review.tests.doubles import Governing
from bugflow.review.tests.journal import QueryableJournal
from bugflow.review.usecases.publish_findings import (
    MANAGED_LABELS,
    NOTHING_NEW,
    PublishFindingsUseCase,
    cited_clauses,
    commit_status_for,
    marker_for,
    resolved_since,
    review_label,
    verdict_for,
)
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="orchard", repo="pear-tree", number=6)
RUN = Correlation(workflow_id="pr/6", run_id="run-1")
PROSE = "prose"
HEAD = "c" * 40
GIT_3 = "**RULE-103. Kernel-style commit messages.**"


class FixedClock:
    def now(self) -> datetime:
        return datetime(2030, 9, 11, tzinfo=UTC)


def finding(
    severity: str,
    message: str = "a finding",
    policy_id: str = "C-03",
    subject: str = "0123456",
) -> Finding:
    return Finding(
        policy_id=policy_id,
        severity=severity,  # type: ignore[arg-type]
        clause="RULE-103",
        subject=subject,
        message=message,
    )


class RecordingForge:
    def __init__(self) -> None:
        self.comments: list[tuple[str, str]] = []
        self.label_calls: list[tuple[frozenset[str], frozenset[str]]] = []
        self.statuses: list[tuple[str, str, str, str]] = []

    def add_comment(self, ref: PullRequestRef, marker: str, body: str) -> int:
        self.comments.append((marker, body))
        return 42

    def set_labels(
        self,
        ref: PullRequestRef,
        add: frozenset[str],
        remove: frozenset[str],
    ) -> None:
        self.label_calls.append((add, remove))

    def set_commit_status(
        self,
        ref: PullRequestRef,
        sha: str,
        context: str,
        state: CommitState,
        description: str,
    ) -> None:
        self.statuses.append((sha, context, state, description))


AGENTS = {"prose": ("C-03", "P-01", "Q-01")}
GOVERNING = ("prose",)


POLICIES = ("C-01", "C-03", "C-05", "P-01", "P-03", "P-04", "Q-01")


def request(
    *findings: Finding,
    run: Correlation = RUN,
    head_sha: str | None = HEAD,
    answered: tuple[str, ...] = POLICIES,
) -> PublishFindingsRequest:
    return PublishFindingsRequest(
        ref=REF,
        findings=findings,
        judge_status="skipped: no judge configured",
        corpus_version="corpus-1",
        correlation=run,
        head_sha=head_sha,
        answered=answered,
    )


OBSERVE = Enforcement(publishes=False, fails_at=None)
ADVISE = Enforcement(publishes=True, fails_at=None)
GATE = Enforcement(publishes=True, fails_at="fail")


class BoundTo:
    def __init__(self, enforcement: Enforcement) -> None:
        self._enforcement = enforcement

    def enforcement_for(self, forge: str, repo: str) -> Enforcement:
        return self._enforcement


def publisher(
    forge: RecordingForge | None = None,
    journal: QueryableJournal | None = None,
    enabled: bool = False,
    agents: dict[str, tuple[str, ...]] | None = None,
    governing: tuple[str, ...] = GOVERNING,
    enforcement: Enforcement | None = None,
    submissions: "Submissions | None" = None,
) -> PublishFindingsUseCase:
    bound = enforcement or (GATE if enabled else OBSERVE)
    return PublishFindingsUseCase(
        forge or RecordingForge(),
        journal if journal is not None else QueryableJournal(),
        FixedClock(),
        enforcement=BoundTo(bound),
        agents=AGENTS if agents is None else agents,
        governance=Governing(*governing),
        submissions=submissions,
    )


class Submissions:
    def __init__(self, **texts: Submission) -> None:
        self._texts = texts

    def get(self, reference: SubmissionRef) -> Submission:
        try:
            return self._texts[reference.snapshot_id]
        except KeyError:
            raise SubmissionNotFoundError(reference.snapshot_id) from None


def says(body: str, *messages: str) -> Submission:
    return Submission(
        title="Add a poller",
        body=body,
        commits=tuple(
            SubmissionCommit(sha=f"{n:040x}", message=m)
            for n, m in enumerate(messages)
        ),
        files=(
            SubmissionFile(
                path="src/poller.py", additions=1, deletions=0, patch=None
            ),
        ),
    )


def quoting(quote: str, severity: str = "warn", subject: str = "") -> Finding:
    return finding(
        severity,
        f'"{quote}": marketing register.',
        policy_id="P-01",
        subject=subject or f'description "{quote}"',
    )


def label_for(*findings: Finding, unavailable: tuple[str, ...] = ()) -> str:
    return review_label(HEAD, AGENTS, GOVERNING, findings, unavailable)


def test_the_worst_severity_an_agent_raised_decides_the_label() -> None:
    assert label_for(finding("warn"), finding("fail")) == "review:escalate"
    assert label_for(finding("info"), finding("warn")) == "review:pass"
    assert label_for(finding("info")) == "review:pass"
    assert label_for() == "review:pass"


def test_a_warn_does_not_hold_a_pull_request() -> None:
    assert label_for(finding("warn")) == "review:pass"


def test_an_agent_that_could_not_answer_leaves_it_in_progress() -> None:
    assert label_for(unavailable=("C-03",)) == "review:wip"
    assert label_for(finding("warn"), unavailable=("P-01",)) == "review:wip"


def test_a_commit_nothing_can_be_keyed_to_is_in_progress() -> None:
    assert review_label(None, AGENTS, GOVERNING, ()) == "review:wip"


def test_a_repository_nothing_governs_has_not_passed() -> None:
    assert review_label(HEAD, AGENTS, (), ()) == "review:wip"


def test_an_agent_with_no_policies_derives_no_verdict() -> None:
    assert verdict_for("safety", (), HEAD, ()) is None


def test_a_governing_checkout_agent_that_reported_nothing_holds_it() -> None:
    agents = {**AGENTS, "safety": ()}
    governing = (*GOVERNING, "safety")
    assert review_label(HEAD, agents, governing, ()) == "review:wip"
    graded = ReviewVerdict(agent_id="safety", head_sha=HEAD, status="pass")
    assert (
        review_label(HEAD, agents, governing, (), reported=(graded,))
        == "review:pass"
    )


def test_an_advisory_agent_neither_holds_nor_escalates() -> None:
    agents = {**AGENTS, "pedagogy": ("PED-01",)}
    findings = (finding("fail", policy_id="PED-01"),)
    assert review_label(HEAD, agents, GOVERNING, findings) == "review:pass"


def test_a_new_finding_is_posted_and_the_label_set() -> None:
    forge = RecordingForge()
    response = publisher(forge, enabled=True).execute(request(finding("warn")))
    assert (response.status, response.comment_id) == ("published", 42)
    ((marker, body),) = forge.comments
    assert marker == marker_for(RUN, "review") and body.startswith(marker)
    assert marker_for(RUN, PROSE) in body
    ((add, remove),) = forge.label_calls
    assert add == {"review:pass"}
    assert remove == MANAGED_LABELS - {"review:pass"}


def test_disabled_publishing_writes_nothing_but_says_what_it_would() -> None:
    forge = RecordingForge()
    response = publisher(forge).execute(request(finding("fail")))
    assert response.status == "skipped: publishing disabled"
    assert response.label == "review:escalate"
    assert marker_for(RUN, PROSE) in response.comment
    assert forge.comments == [] and forge.label_calls == []


def test_the_worst_is_said_first_and_nothing_is_for_a_machine() -> None:
    body = (
        publisher()
        .execute(
            request(finding("info", "big diff"), finding("fail", "bad prefix"))
        )
        .comment
    )
    assert body.index("Bad prefix") < body.index("Big diff")
    visible = body.split("-->", 1)[1]
    for code in ("corpus-1", "run-1", "pr/github", "C-03", "RULE-103"):
        assert code not in visible, code


def test_a_clean_first_review_is_said_once() -> None:
    forge = RecordingForge()
    journal = QueryableJournal()
    publish = publisher(forge, journal=journal, enabled=True)

    first = publish.execute(request())
    second = publish.execute(request(run=SECOND))

    assert "**Prose review: nothing to raise.**" in first.comment
    assert second.comment == "" and second.status == NOTHING_NEW
    assert len(forge.comments) == 1
    ((add, _), _) = forge.label_calls
    assert add == {"review:pass"}


def test_until_a_comment_is_posted_every_evaluation_is_a_first_word() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal)
    stands = finding("warn", "long line")
    raised(journal, RUN, stands)
    publish.execute(request(stands, run=RUN))
    assert "Long line" in publish.execute(request(stands, run=SECOND)).comment


def test_a_finding_the_last_evaluation_raised_is_not_raised_again() -> None:
    journal = QueryableJournal()
    forge = RecordingForge()
    publish = publisher(forge, journal=journal, enabled=True)
    stands = finding("warn")
    raised(journal, RUN, stands)
    publish.execute(request(stands, run=RUN))

    response = publish.execute(request(stands, run=SECOND))

    assert response.comment == "" and response.status == NOTHING_NEW
    assert len(forge.comments) == 1


SECOND = Correlation(workflow_id="pr/6", run_id="run-2")


def test_every_action_is_recorded_whether_or_not_it_was_performed() -> None:
    for enabled in (True, False):
        journal = QueryableJournal()
        publisher(journal=journal, enabled=enabled).execute(
            request(finding("warn"))
        )
        actions = {
            e.payload["action"]: e
            for e in journal.entries
            if e.event_type == "action.taken"
        }
        assert set(actions) == {
            "review_comment",
            "outcome_label",
            "commit_status",
        }
        assert all(a.payload["performed"] is enabled for a in actions.values())
        assert actions["outcome_label"].payload["label"] == "review:pass"
        assert all(a.corpus_version == "corpus-1" for a in actions.values())


def test_a_retried_publish_records_its_actions_once() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal)
    publish.execute(request(finding("warn")))
    publish.execute(request(finding("warn")))
    assert sum(e.event_type == "action.taken" for e in journal.entries) == 3


def test_each_violation_is_resolved_on_its_own() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal, enabled=True)
    first = finding("warn", "past tense", subject='summary "Added it"')
    second = finding("warn", "a noun phrase", subject='summary "Support"')
    raised(journal, RUN, first, second)
    publish.execute(request(first, second, run=RUN))

    response = publish.execute(request(second, run=SECOND))

    assert response.resolved == (first,)
    assert "1 passage fixed since the last review" in response.comment
    assert "past tense" in response.comment
    assert "a noun phrase" not in response.comment


def test_one_passage_under_two_clauses_is_two_findings_to_resolve() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal)
    both = 'description "Simple, but not simplistic."'
    aphorism = finding("warn", "cadence, not content", subject=both)
    antithesis = replace(aphorism, clause="RULE-27")
    raised(journal, RUN, aphorism, antithesis)
    publish.execute(request(aphorism, antithesis, run=RUN))

    response = publish.execute(request(antithesis, run=SECOND))

    assert response.resolved == (aphorism,)


def raised(
    journal: QueryableJournal, run: Correlation, *found: Finding
) -> None:
    recorder = Recorder(REF, run, "corpus-1", FixedClock().now())
    journal.append(recorder.findings("deterministic", found))


def test_a_finding_absent_from_this_evaluation_is_resolved() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal, enabled=True)
    fixed = finding("fail", "bad prefix", subject="aaaaaaa")
    kept = finding("warn", "long line", policy_id="C-05")
    raised(journal, RUN, fixed, kept)
    publish.execute(request(fixed, kept, run=RUN))

    response = publish.execute(request(kept, run=SECOND))

    assert response.resolved == (fixed,)
    (entry,) = [
        e for e in journal.entries if e.event_type == "finding.resolved"
    ]
    assert (entry.run_id, entry.payload["raised_in_run_id"]) == (
        "run-2",
        "run-1",
    )
    assert entry.payload["subject"] == "aaaaaaa"
    assert "fixed since the last review" in response.comment
    assert "bad prefix" in response.comment
    assert "long line" not in response.comment
    assert "**Prose review:** 1 warning." in response.comment


def test_resolution_compares_with_the_latest_evaluation_only() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal)
    fixed = finding("fail", subject="aaaaaaa")
    raised(journal, RUN, fixed)
    publish.execute(request(fixed, run=RUN))
    publish.execute(request(run=SECOND))

    third = Correlation(workflow_id="pr/6", run_id="run-3")
    assert publish.execute(request(run=third)).resolved == ()


def test_the_first_evaluation_resolves_nothing() -> None:
    journal = QueryableJournal()
    response = publisher(journal=journal).execute(request())
    assert response.resolved == ()
    assert "fixed" not in response.comment
    assert not any(e.event_type == "finding.resolved" for e in journal.entries)


def test_a_changed_message_is_the_same_finding() -> None:
    before = [finding("info", "diff of 900 lines")]
    after = [finding("info", "diff of 950 lines")]
    assert resolved_since(before, after, POLICIES) == ()


def dismiss(
    journal: QueryableJournal,
    policy_id: str,
    reason: str,
    ref: PullRequestRef = REF,
) -> None:
    delivery = Correlation(workflow_id="delivery/github", run_id="c-1")
    recorder = Recorder(ref, delivery, None, FixedClock().now())
    journal.append(
        [
            recorder.entry(
                "finding.dismissed",
                f"c-1/{policy_id}",
                {
                    "policy_id": policy_id,
                    "reason": reason,
                    "actor": "reviewer",
                    "comment_id": 99,
                    "delivery_id": "c-1",
                },
            )
        ]
    )


NARRATES = finding(
    "warn", "narrates", policy_id="P-01", subject="description (RULE-19)"
)


def test_a_dismissed_policy_is_not_reported_again_or_labelled() -> None:
    journal = QueryableJournal()
    dismiss(journal, "P-01", "evidence, not narration")
    response = publisher(journal=journal).execute(
        request(NARRATES, finding("info", "big diff", policy_id="Q-03"))
    )
    assert response.label == "review:pass"
    assert response.dismissed == (NARRATES,)
    assert "narrates" not in response.comment
    assert "Big diff" in response.comment


def test_a_dismissed_finding_going_away_is_not_thanked_for() -> None:
    journal = QueryableJournal()
    dismiss(journal, "P-01", "evidence, not narration")
    raised(journal, RUN, NARRATES)
    publish = publisher(journal=journal, enabled=True)
    publish.execute(request(NARRATES, run=RUN))

    response = publish.execute(request(run=SECOND))

    assert response.comment == ""


def test_a_dismissal_on_another_pull_request_does_not_apply() -> None:
    journal = QueryableJournal()
    other = PullRequestRef(owner="orchard", repo="pear-tree", number=7)
    dismiss(journal, "P-01", "evidence, not narration", ref=other)
    response = publisher(journal=journal).execute(request(NARRATES))
    assert response.label == "review:pass"
    assert response.dismissed == ()


def test_the_journal_counts_the_dismissed_findings() -> None:
    journal = QueryableJournal()
    dismiss(journal, "P-01", "evidence, not narration")
    publisher(journal=journal).execute(request(NARRATES))
    (summary,) = [
        e
        for e in journal.entries
        if e.event_type == "action.taken"
        and e.payload["action"] == "review_comment"
    ]
    assert summary.payload["dismissed_count"] == 1


def test_only_a_failing_finding_fails_the_commit_status() -> None:
    assert commit_status_for([finding("fail"), finding("warn")]) == (
        "failure",
        "1 failing finding, 1 warning",
    )
    assert commit_status_for([finding("warn"), finding("warn")]) == (
        "success",
        "2 warnings; advisory",
    )
    assert commit_status_for([finding("info")]) == ("success", "no findings")


def test_publishing_sets_the_commit_status_on_the_head_commit() -> None:
    forge = RecordingForge()
    journal = QueryableJournal()
    publisher(forge, journal, enabled=True).execute(request(finding("fail")))
    assert forge.statuses == [(HEAD, PROSE, "failure", "1 failing finding")]
    (entry,) = [
        e
        for e in journal.entries
        if e.event_type == "action.taken"
        and e.payload["action"] == "commit_status"
    ]
    assert entry.commit_sha == HEAD
    assert (entry.payload["performed"], entry.payload["state"]) == (
        True,
        "failure",
    )


def test_a_dismissed_policy_does_not_fail_the_commit_status() -> None:
    forge = RecordingForge()
    journal = QueryableJournal()
    dismissal = Recorder(REF, RUN, None, FixedClock().now()).entry(
        "finding.dismissed",
        "d-1",
        {"policy_id": "C-03", "reason": "a reason", "actor": "reviewer"},
    )
    journal.append([dismissal])
    publisher(forge, journal, enabled=True).execute(request(finding("fail")))
    assert forge.statuses == [(HEAD, PROSE, "success", "no findings")]


def test_without_a_head_commit_no_status_is_set() -> None:
    forge = RecordingForge()
    journal = QueryableJournal()
    publisher(forge, journal, enabled=True).execute(request(head_sha=None))
    assert forge.statuses == []
    (entry,) = [
        e
        for e in journal.entries
        if e.event_type == "action.taken"
        and e.payload["action"] == "commit_status"
    ]
    assert entry.payload["status"] == "skipped: no head commit"


class StatusRefusingForge(RecordingForge):
    def set_commit_status(
        self,
        ref: PullRequestRef,
        sha: str,
        context: str,
        state: CommitState,
        description: str,
    ) -> None:
        raise PublicationRejectedError("GitHub returned 403 for the status")


def test_a_refused_status_leaves_the_comment_and_label_published() -> None:
    forge = StatusRefusingForge()
    journal = QueryableJournal()
    response = publisher(forge, journal, enabled=True).execute(
        request(finding("warn"))
    )
    assert response.status == "published"
    assert forge.comments and forge.label_calls
    (entry,) = [
        e
        for e in journal.entries
        if e.event_type == "action.taken"
        and e.payload["action"] == "commit_status"
    ]
    assert entry.payload["performed"] is False
    assert entry.payload["status"].startswith("rejected: GitHub returned 403")


def test_an_evaluation_that_must_not_publish_writes_nothing() -> None:
    forge = RecordingForge()
    journal = QueryableJournal()
    unpublished = request(finding("fail")).model_copy(
        update={"publish": False}
    )
    response = publisher(forge, journal, enabled=True).execute(unpublished)
    assert response.status == "skipped: not published for this evaluation"
    assert response.label == "review:escalate"
    assert forge.comments == []
    assert forge.label_calls == []
    assert forge.statuses == []
    actions = [e for e in journal.entries if e.event_type == "action.taken"]
    assert len(actions) == 3
    assert not any(a.payload["performed"] for a in actions)


UNANSWERED = ("P-01", "C-01")


def unanswered_request(*findings: Finding) -> PublishFindingsRequest:
    return request(
        *findings,
        answered=tuple(p for p in POLICIES if p not in UNANSWERED),
    ).model_copy(update={"unavailable": UNANSWERED})


def test_a_policy_the_judge_could_not_answer_is_not_a_pass() -> None:
    forge = RecordingForge()
    response = publisher(forge, enabled=True).execute(unanswered_request())
    assert response.label == "review:wip"
    ((add, remove),) = forge.label_calls
    assert add == {"review:wip"}
    assert remove == MANAGED_LABELS - {"review:wip"}


def test_a_fail_outranks_an_unanswered_policy() -> None:
    assert label_for(finding("fail"), unavailable=UNANSWERED) == (
        "review:escalate"
    )


def test_the_commit_status_names_the_unanswered_policies() -> None:
    state, description = commit_status_for([], UNANSWERED)
    assert state == "success"
    assert (
        description == "nothing assessed; 2 policies unanswered (C-01, P-01)"
    )


def test_an_outage_of_ours_does_not_fail_the_pull_request() -> None:
    state, _ = commit_status_for([finding("warn")], UNANSWERED)
    assert state == "success"


def test_an_unanswered_policy_is_not_commented_on() -> None:
    response = publisher(enabled=True).execute(unanswered_request())
    assert response.comment == ""


def test_an_unanswered_policy_resolves_nothing() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal)
    earlier = finding("fail", "bad prefix", policy_id="P-01")
    raised(journal, RUN, earlier)
    publish.execute(request(earlier, run=RUN))

    response = publish.execute(
        request(
            run=SECOND,
            answered=tuple(p for p in POLICIES if p != "P-01"),
        ).model_copy(update={"unavailable": ("P-01",)})
    )

    assert response.resolved == ()
    assert response.comment == ""
    assert not any(e.event_type == "finding.resolved" for e in journal.entries)


def test_a_policy_that_did_not_run_resolves_nothing() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal)
    earlier = finding("fail", "bad prefix", policy_id="P-01")
    raised(journal, RUN, earlier)
    publish.execute(request(earlier, run=RUN))

    response = publish.execute(request(run=SECOND, answered=()))

    assert response.resolved == ()
    assert not any(e.event_type == "finding.resolved" for e in journal.entries)


def test_a_policy_that_ran_and_found_nothing_resolves_its_findings() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal)
    earlier = finding("fail", "bad prefix", policy_id="P-01")
    raised(journal, RUN, earlier)
    publish.execute(request(earlier, run=RUN))

    response = publish.execute(request(run=SECOND, answered=("P-01",)))

    assert response.resolved == (earlier,)
    assert [
        e.payload["policy_id"]
        for e in journal.entries
        if e.event_type == "finding.resolved"
    ] == ["P-01"]


def test_one_policy_answering_does_not_withdraw_another_s_findings() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal)
    answered = finding("fail", "bad prefix", policy_id="P-01")
    silent = finding("warn", "long line", policy_id="C-05")
    raised(journal, RUN, answered, silent)
    publish.execute(request(answered, silent, run=RUN))

    response = publish.execute(request(run=SECOND, answered=("P-01",)))

    assert response.resolved == (answered,)


NARRATION = Finding(
    policy_id="P-01",
    severity="warn",
    clause="RULE-19",
    subject='description "measured and discarded"',
    message='"measured and discarded": The text narrates false starts.',
    judged_by="a-model",
)
CLAUSES = {
    "RULE-19": "**RULE-19. Narrating yourself.** Descriptions describe "
    "the change, not the process of arriving at it.",
    "RULE-104": "**RULE-104. One reason.** A commit is one reason's worth of "
    "change.",
}


def cited(*findings: Finding) -> PublishFindingsRequest:
    return request(*findings).model_copy(update={"clauses": CLAUSES})


def test_a_rule_is_stated_once_with_its_violations_under_it() -> None:
    body = publisher().execute(cited(NARRATION)).comment
    assert (
        "**Narrating yourself.** Descriptions describe the change, not the "
        "process of arriving at it." in body
    )
    assert (
        '- **Warning.** In the description: "measured and discarded"\\\n'
        "  The text narrates false starts." in body
    )
    assert "RULE-19" not in body.split("-->", 1)[1]


def test_a_named_rule_is_named_and_an_unnamed_one_summarised() -> None:
    publish = PublishFindingsUseCase(
        RecordingForge(),
        QueryableJournal(),
        FixedClock(),
        enforcement=BoundTo(OBSERVE),
        agents=AGENTS,
        governance=Governing(*GOVERNING),
        summaries={
            "P-01": "The title and description read as an engineer wrote them"
        },
    )
    named = publish.execute(cited(NARRATION)).comment
    assert "**Narrating yourself.**" in named
    unnamed = publish.execute(
        request(replace(NARRATION, clause="RULE-2"))
    ).comment
    assert (
        "**The title and description read as an engineer wrote them.**"
        in unnamed
    )


def dash(quote: str) -> Finding:
    return Finding(
        policy_id="P-04",
        severity="warn",
        clause="RULE-21",
        subject=f'description "{quote}"',
        message=f'"{quote}": an em dash stands here where a colon belongs.',
    )


def test_one_fault_in_many_passages_is_said_once() -> None:
    body = (
        publisher()
        .execute(
            request(
                dash(
                    "sured yet — they need a calibration run against "
                    "Haiku to sa"
                ),
                dash(
                    "her model — and fixing it should make the policy "
                    "better on"
                ),
            )
        )
        .comment
    )
    assert body.count("An em dash stands here") == 1
    assert body.count("- **Warning.** In the description:") == 2
    assert '"…yet — they need a calibration run against Haiku to…"' in body


SNAPSHOT = "s" * 64


def observed(
    journal: QueryableJournal,
    run: Correlation,
    corpus: str = "corpus-1",
    head: str | None = HEAD,
    snapshot: str = SNAPSHOT,
) -> None:
    recorder = Recorder(REF, run, corpus, FixedClock().now())
    journal.append(
        [
            recorder.entry(
                "pr.observed",
                "observed",
                {"snapshot_id": snapshot},
                commit_sha=head,
            )
        ]
    )


def rejudge(corpus: str, *findings: Finding) -> PublishFindingsRequest:
    return request(*findings, run=SECOND).model_copy(
        update={"snapshot_id": SNAPSHOT, "corpus_version": corpus}
    )


def test_a_new_judge_on_the_same_text_says_nothing_unless_it_differs() -> None:
    journal = QueryableJournal()
    forge = RecordingForge()
    publish = publisher(forge, journal=journal, enabled=True)
    stands = finding("warn", "long line")
    raised(journal, RUN, stands)
    observed(journal, RUN, "corpus-1")
    publish.execute(request(stands, run=RUN))

    again = publish.execute(
        rejudge("0ld0ld0ld0ld", finding("warn", "a different reading"))
    )

    assert again.comments == {}
    assert len(forge.comments) == 1


def test_a_new_judge_that_moves_the_verdict_says_so() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal, enabled=True)
    stands = finding("warn", "long line")
    raised(journal, RUN, stands)
    observed(journal, RUN, "corpus-1")
    publish.execute(request(stands, run=RUN))

    again = publish.execute(rejudge("0ld0ld0ld0ld", finding("fail", "worse")))

    body = again.comments["prose"]
    assert "has not changed since the last review" in body
    assert "Worse" in body


def test_a_clause_the_doctrine_does_not_carry_is_left_out() -> None:
    body = publisher().execute(request(NARRATION)).comment
    assert "The text narrates false starts." in body
    assert "RULE-19. Narrating" not in body


def test_the_doctrine_gives_a_clause_as_it_is_written() -> None:
    doctrine = DoctrineText(
        text="# Voice\n\n**RULE-19. Narrating yourself.** Describe the\n"
        "change, not the process.\n\n**RULE-20. Triples.** No.\n"
    )
    assert doctrine.clause("RULE-19") == (
        "**RULE-19. Narrating yourself.** Describe the\nchange, not the "
        "process."
    )
    assert doctrine.clause("RULE-99") is None


def test_the_doctrine_gives_a_clause_that_has_no_name() -> None:
    doctrine = DoctrineText(
        text="**RULE-2.** State the thing.\n\n**RULE-21. Em dashes.** No."
    )
    assert doctrine.clause("RULE-2") == "**RULE-2.** State the thing."
    assert doctrine.clause("RULE-21") == "**RULE-21. Em dashes.** No."


def test_only_the_clauses_the_findings_cite_are_carried() -> None:
    doctrine = DoctrineText(
        text="**RULE-19. Narrating yourself.** Describe the change.\n\n"
        "**RULE-20. Triples.** No.\n"
    )
    assert set(cited_clauses(doctrine, [NARRATION])) == {"RULE-19"}


def test_the_rule_with_the_worst_violation_comes_first() -> None:
    again = replace(
        NARRATION, clause="RULE-104", severity="fail", policy_id="Q-01"
    )
    body = publisher().execute(cited(NARRATION, again)).comment
    assert body.index("**One reason.**") < body.index(
        "**Narrating yourself.**"
    )
    assert body.count('"measured and discarded"') == 2


SAFETY = "safety"
NOTE = (
    "wait() reads a session's status by an id the platform returned, so "
    "nothing outside can choose it."
)


def reviewed(
    status: str = "pass",
    note: str = NOTE,
    write_up: str = "",
    run: Correlation = RUN,
    head_sha: str = HEAD,
) -> PublishFindingsRequest:
    return request(run=run, head_sha=head_sha).model_copy(
        update={
            "verdicts": (
                ReviewVerdict(
                    agent_id=SAFETY,
                    head_sha=head_sha,
                    status=status,  # type: ignore[arg-type]
                ),
            ),
            "notes": (
                ReviewNote(
                    agent_id=SAFETY,
                    head_sha=head_sha,
                    note=note,
                    write_up=write_up,
                ),
            ),
        }
    )


def with_safety(forge: RecordingForge, journal: QueryableJournal):  # type: ignore[no-untyped-def]
    return publisher(
        forge,
        journal=journal,
        enforcement=GATE,
        agents={**AGENTS, SAFETY: ()},
    )


def test_a_checkout_agent_speaks_for_itself() -> None:
    forge = RecordingForge()
    response = with_safety(forge, QueryableJournal()).execute(reviewed())
    assert response.comments[SAFETY].endswith(
        f"**Safety review: nothing to raise.** {NOTE}\n"
    )
    assert NOTE not in response.comments[PROSE]
    assert (HEAD, SAFETY, "success", "nothing to raise") in forge.statuses


def test_a_checkout_agent_says_a_clean_review_once() -> None:
    forge = RecordingForge()
    journal = QueryableJournal()
    publish = with_safety(forge, journal)
    publish.execute(reviewed())
    later = publish.execute(reviewed(run=SECOND, head_sha="d" * 40))
    assert SAFETY not in later.comments


def test_a_checkout_agent_speaks_again_when_its_verdict_changes() -> None:
    forge = RecordingForge()
    journal = QueryableJournal()
    publish = with_safety(forge, journal)
    publish.execute(reviewed())
    later = publish.execute(
        reviewed("fail", note="A token in a URL.", run=SECOND)
    )
    assert "**Safety review: a problem to fix.**" in later.comments[SAFETY]


def test_an_advisory_checkout_agent_never_fails_a_commit() -> None:
    forge = RecordingForge()
    with_safety(forge, QueryableJournal()).execute(reviewed("fail"))
    assert (
        HEAD,
        SAFETY,
        "success",
        "a problem to fix; advisory",
    ) in forge.statuses


def test_without_a_note_fit_to_show_the_write_up_is_folded() -> None:
    response = with_safety(RecordingForge(), QueryableJournal()).execute(
        reviewed(note="", write_up="I read the diff. Nothing reachable.")
    )
    body = response.comments[SAFETY]
    assert "**Safety review: nothing to raise.**\n" in body
    assert "<details><summary>The review</summary>" in body
    assert "Nothing reachable." in body


STALE = ReviewVerdict(agent_id="safety", head_sha="0" * 40, status="pass")
LABEL_ABSENCES: dict[str, Callable[[], str]] = {
    "no head commit": lambda: review_label(None, AGENTS, GOVERNING, ()),
    "nothing governs": lambda: review_label(HEAD, AGENTS, (), ()),
    "a governing policy went unanswered": lambda: review_label(
        HEAD, AGENTS, GOVERNING, (), unavailable=AGENTS["prose"][:1]
    ),
    "a checkout agent reported nothing": lambda: review_label(
        HEAD, {**AGENTS, "safety": ()}, (*GOVERNING, "safety"), ()
    ),
    "a governing agent is not installed": lambda: review_label(
        HEAD, AGENTS, (*GOVERNING, "safety"), ()
    ),
    "the only verdict is about an older commit": lambda: review_label(
        HEAD,
        {**AGENTS, "safety": ()},
        (*GOVERNING, "safety"),
        (),
        reported=(STALE,),
    ),
}


@pytest.mark.parametrize("absence", sorted(LABEL_ABSENCES))
def test_no_missing_verdict_is_a_pass(absence: str) -> None:
    assert LABEL_ABSENCES[absence]() == "review:wip", absence


def test_under_advise_a_failing_finding_is_published_and_fails_nothing() -> (
    None
):
    forge = RecordingForge()
    response = publisher(forge, enforcement=ADVISE).execute(
        request(finding("fail"))
    )
    assert response.status == "published"
    assert len(forge.comments) == 1
    assert forge.statuses == [
        (HEAD, PROSE, "success", "1 failing finding; advisory")
    ]


def test_under_observe_nothing_reaches_the_forge() -> None:
    forge = RecordingForge()
    response = publisher(forge, enforcement=OBSERVE).execute(
        request(finding("fail"))
    )
    assert response.status == "skipped: publishing disabled"
    assert forge.comments == [] and forge.statuses == []


THIRD = Correlation(workflow_id="pr/6", run_id="run-3")


def test_a_finding_that_arrived_late_at_one_commit_is_not_announced() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal, enabled=True)
    stands = finding("warn", "long line")
    flicker = finding("warn", "manufactured antithesis", policy_id="P-01")
    observed(journal, RUN)
    raised(journal, RUN, stands)
    publish.execute(request(stands, run=RUN))

    observed(journal, SECOND)
    raised(journal, SECOND, stands, flicker)
    response = publish.execute(request(stands, flicker, run=SECOND))

    assert "Manufactured antithesis" not in response.comment


def test_what_stood_in_every_evaluation_is_still_announced() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal, enabled=True)
    stands = finding("warn", "long line")
    arrives = finding("warn", "unresolved reference", policy_id="P-01")
    observed(journal, RUN)
    raised(journal, RUN, stands)
    publish.execute(request(stands, run=RUN))

    observed(journal, SECOND)
    raised(journal, SECOND, stands, arrives)
    publish.execute(request(stands, arrives, run=SECOND))
    observed(journal, THIRD)
    raised(journal, THIRD, stands, arrives)
    response = publish.execute(request(stands, arrives, run=THIRD))

    assert "Unresolved reference" not in response.comment


def test_one_comment_carries_every_reviewer() -> None:
    forge = RecordingForge()
    journal = QueryableJournal()
    agents = {**AGENTS, "safety": ()}
    publish = publisher(
        forge,
        journal=journal,
        enabled=True,
        agents=agents,
        governing=("prose", "safety"),
    )
    verdicts = (
        ReviewVerdict(agent_id="safety", head_sha=HEAD, status="warn"),
    )
    notes = (
        ReviewNote(
            agent_id="safety",
            head_sha=HEAD,
            note="The token is read from the environment.",
        ),
    )
    publish.execute(
        request(finding("warn", "long line")).model_copy(
            update={"verdicts": verdicts, "notes": notes}
        )
    )

    assert len(forge.comments) == 1
    ((_, body),) = forge.comments
    assert "Prose review" in body and "Safety review" in body

    posted = [
        e.payload
        for e in journal.entries
        if e.payload.get("action") == "review_comment"
        and e.payload.get("performed")
    ]
    assert {p["agent_id"] for p in posted} == {"prose", "safety"}
    assert len({p["comment_id"] for p in posted}) == 1


def test_a_description_rewritten_on_one_commit_is_read_as_new_text() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal, enabled=True)
    before = finding("fail", "unresolved reference", subject="old passage")
    after = finding("warn", "long line", subject="new passage")
    observed(journal, RUN, snapshot="a" * 64)
    raised(journal, RUN, before)
    publish.execute(
        request(before, run=RUN).model_copy(update={"snapshot_id": "a" * 64})
    )

    observed(journal, SECOND, snapshot="b" * 64)
    raised(journal, SECOND, after)
    response = publish.execute(
        request(after, run=SECOND).model_copy(update={"snapshot_id": "b" * 64})
    )

    assert "Long line" in response.comment
    assert "fixed since the last review" in response.comment


def test_a_finding_still_standing_is_named_when_nothing_is_new() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal, enabled=True)
    stays = finding("warn", "long line", subject="kept passage")
    goes = finding("fail", "unresolved reference", subject="gone passage")
    observed(journal, RUN, snapshot="a" * 64)
    raised(journal, RUN, stays, goes)
    publish.execute(request(stays, goes, run=RUN))

    observed(journal, SECOND, snapshot="b" * 64)
    raised(journal, SECOND, stays)
    response = publish.execute(request(stays, run=SECOND))

    assert "**Prose review:** 1 warning." in response.comment
    assert "One, raised earlier, still stands." in response.comment


def test_a_withheld_finding_is_not_counted_in_the_comment() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal, enabled=True)
    stands = finding("warn", "long line")
    flicker = finding("warn", "manufactured antithesis", policy_id="P-01")
    fixed = finding("fail", "unresolved reference", subject="gone")
    observed(journal, RUN)
    raised(journal, RUN, stands, fixed)
    publish.execute(request(stands, fixed, run=RUN))

    observed(journal, SECOND)
    raised(journal, SECOND, stands, flicker)
    response = publish.execute(request(stands, flicker, run=SECOND))

    assert "**Prose review:** 1 warning." in response.comment
    assert "Manufactured antithesis" not in response.comment


def test_a_passage_no_longer_said_is_recorded_as_rewritten() -> None:
    journal = QueryableJournal()
    texts = Submissions(
        a=says("Adds a seamless poller.\nRobust too."),
        b=says("Adds a poller.\nRobust too."),
    )
    publish = publisher(journal=journal, enabled=True, submissions=texts)
    gone = quoting("seamless poller")
    stays = quoting("Robust too")
    unquoted = finding("warn", "long line")
    observed(journal, RUN, snapshot="a")
    raised(journal, RUN, gone, stays, unquoted)
    publish.execute(
        request(gone, stays, unquoted, run=RUN).model_copy(
            update={"snapshot_id": "a"}
        )
    )

    observed(journal, SECOND, snapshot="b")
    publish.execute(
        request(stays, unquoted, run=SECOND).model_copy(
            update={"snapshot_id": "b"}
        )
    )

    (entry,) = [
        e for e in journal.entries if e.event_type == "finding.rewritten"
    ]
    assert entry.payload["subject"] == gone.subject
    assert (entry.run_id, entry.payload["raised_in_run_id"]) == (
        "run-2",
        "run-1",
    )


def test_a_passage_the_judge_stopped_flagging_is_not_rewritten() -> None:
    journal = QueryableJournal()
    texts = Submissions(a=says("Adds a seamless poller."))
    publish = publisher(journal=journal, enabled=True, submissions=texts)
    flagged = quoting("seamless poller")
    observed(journal, RUN, snapshot="a")
    raised(journal, RUN, flagged)
    publish.execute(
        request(flagged, run=RUN).model_copy(update={"snapshot_id": "a"})
    )

    observed(journal, SECOND, snapshot="a")
    response = publish.execute(
        request(run=SECOND).model_copy(update={"snapshot_id": "a"})
    )

    assert response.resolved == (flagged,)
    assert not any(
        e.event_type == "finding.rewritten" for e in journal.entries
    )


def test_a_passage_quoted_without_its_markup_still_stands() -> None:
    journal = QueryableJournal()
    texts = Submissions(a=says("Adds a **seamless** `poller`."))
    publish = publisher(journal=journal, enabled=True, submissions=texts)
    flagged = quoting("seamless poller")
    observed(journal, RUN, snapshot="a")
    raised(journal, RUN, flagged)
    publish.execute(
        request(flagged, run=RUN).model_copy(update={"snapshot_id": "a"})
    )
    observed(journal, SECOND, snapshot="a")
    publish.execute(
        request(flagged, run=SECOND).model_copy(update={"snapshot_id": "a"})
    )
    assert not any(
        e.event_type == "finding.rewritten" for e in journal.entries
    )


def test_a_rewrite_is_recorded_once_for_one_finding() -> None:
    journal = QueryableJournal()
    texts = Submissions(a=says("seamless poller"), b=says("poller"))
    publish = publisher(journal=journal, enabled=True, submissions=texts)
    gone = quoting("seamless poller")
    observed(journal, RUN, snapshot="a")
    raised(journal, RUN, gone)
    publish.execute(
        request(gone, run=RUN).model_copy(update={"snapshot_id": "a"})
    )
    observed(journal, SECOND, snapshot="b")
    raised(journal, SECOND, gone)
    publish.execute(
        request(gone, run=SECOND).model_copy(update={"snapshot_id": "b"})
    )
    third = Correlation(workflow_id="pr/6", run_id="run-3")
    observed(journal, third, snapshot="b")
    publish.execute(request(run=third).model_copy(update={"snapshot_id": "b"}))
    assert (
        sum(e.event_type == "finding.rewritten" for e in journal.entries) == 1
    )


def test_without_a_text_to_read_nothing_is_rewritten() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal, enabled=True)
    gone = quoting("seamless poller")
    observed(journal, RUN, snapshot="a")
    raised(journal, RUN, gone)
    publish.execute(
        request(gone, run=RUN).model_copy(update={"snapshot_id": "a"})
    )
    observed(journal, SECOND, snapshot="b")
    publish.execute(
        request(run=SECOND).model_copy(update={"snapshot_id": "b"})
    )
    assert not any(
        e.event_type == "finding.rewritten" for e in journal.entries
    )


WITHHOLDING_ALL = Enforcement(publishes=True, fails_at="fail", withholds=1.0)


def test_a_withheld_warning_reaches_nobody_and_is_journalled() -> None:
    journal, forge = QueryableJournal(), RecordingForge()
    publish = publisher(
        forge=forge, journal=journal, enforcement=WITHHOLDING_ALL
    )
    warned = quoting("seamless poller")
    failed = finding("fail", "bad prefix", subject="aaaaaaa")
    observed(journal, RUN)
    raised(journal, RUN, warned, failed)
    response = publish.execute(request(warned, failed, run=RUN))

    assert response.withheld == (warned,)
    assert "seamless poller" not in response.comment
    assert "1 failure." in response.comment
    assert "warning" not in response.comment
    (_, _, _, description) = forge.statuses[0]
    assert "warning" not in description
    (entry,) = [
        e for e in journal.entries if e.event_type == "finding.withheld"
    ]
    assert entry.payload["subject"] == warned.subject
    assert entry.payload["share"] == 1.0


def test_a_fail_is_published_whatever_the_share() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal, enforcement=WITHHOLDING_ALL)
    failed = finding("fail", "bad prefix", subject="aaaaaaa")
    observed(journal, RUN)
    raised(journal, RUN, failed)
    response = publish.execute(request(failed, run=RUN))

    assert response.withheld == ()
    assert "Bad prefix" in response.comment
    assert response.label == label_for(failed)


def test_a_withheld_warning_going_is_not_thanked_for() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal, enforcement=WITHHOLDING_ALL)
    warned = quoting("seamless poller")
    failed = finding("fail", "bad prefix", subject="aaaaaaa")
    observed(journal, RUN)
    raised(journal, RUN, warned, failed)
    publish.execute(request(warned, failed, run=RUN))

    observed(journal, SECOND)
    raised(journal, SECOND, failed)
    response = publish.execute(request(failed, run=SECOND))

    assert response.resolved == (warned,)
    assert "fixed" not in response.comment
    assert any(e.event_type == "finding.resolved" for e in journal.entries)


def test_a_withheld_warning_is_journalled_when_first_seen_only() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal, enforcement=WITHHOLDING_ALL)
    warned = quoting("seamless poller")
    observed(journal, RUN)
    raised(journal, RUN, warned)
    publish.execute(request(warned, run=RUN))
    observed(journal, SECOND)
    raised(journal, SECOND, warned)
    publish.execute(request(warned, run=SECOND))

    assert (
        sum(e.event_type == "finding.withheld" for e in journal.entries) == 1
    )


def test_with_no_share_declared_every_warning_is_published() -> None:
    journal = QueryableJournal()
    publish = publisher(journal=journal, enabled=True)
    warned = quoting("seamless poller")
    observed(journal, RUN)
    raised(journal, RUN, warned)
    response = publish.execute(request(warned, run=RUN))

    assert response.withheld == ()
    assert "seamless poller" in response.comment
    assert not any(e.event_type == "finding.withheld" for e in journal.entries)


def test_a_judge_gone_quiet_on_standing_words_withdraws_nothing() -> None:
    journal = QueryableJournal()
    texts = Submissions(a=says("Adds a seamless poller."))
    publish = publisher(journal=journal, enabled=True, submissions=texts)
    flagged = quoting("seamless poller")
    observed(journal, RUN, snapshot="a")
    raised(journal, RUN, flagged)
    publish.execute(
        request(flagged, run=RUN).model_copy(update={"snapshot_id": "a"})
    )

    observed(journal, SECOND, snapshot="a")
    response = publish.execute(
        request(run=SECOND).model_copy(update={"snapshot_id": "a"})
    )

    assert response.carried == (flagged,)
    assert response.resolved == (flagged,)
    assert "fixed" not in response.comment
    assert any(e.event_type == "finding.resolved" for e in journal.entries)
    (_, _, _, described) = publish._forge.statuses[-1]  # type: ignore[attr-defined]
    assert "1 warning" in described


def test_a_carried_finding_stands_across_later_evaluations() -> None:
    journal = QueryableJournal()
    texts = Submissions(a=says("Adds a seamless poller."))
    publish = publisher(journal=journal, enabled=True, submissions=texts)
    flagged = quoting("seamless poller")
    observed(journal, RUN, snapshot="a")
    raised(journal, RUN, flagged)
    publish.execute(
        request(flagged, run=RUN).model_copy(update={"snapshot_id": "a"})
    )
    observed(journal, SECOND, snapshot="a")
    publish.execute(
        request(run=SECOND).model_copy(update={"snapshot_id": "a"})
    )
    third = Correlation(workflow_id="pr/6", run_id="run-3")
    observed(journal, third, snapshot="a")
    response = publish.execute(
        request(run=third).model_copy(update={"snapshot_id": "a"})
    )

    assert response.carried == (flagged,)
    assert "fixed" not in response.comment
    assert (
        sum(e.event_type == "finding.resolved" for e in journal.entries) == 1
    )


def test_the_same_words_quoted_differently_are_not_a_new_finding() -> None:
    journal = QueryableJournal()
    texts = Submissions(a=says("Adds a seamless, robust poller."))
    publish = publisher(journal=journal, enabled=True, submissions=texts)
    first = quoting("seamless, robust poller")
    again = quoting("robust poller")
    observed(journal, RUN, snapshot="a")
    raised(journal, RUN, first)
    publish.execute(
        request(first, run=RUN).model_copy(update={"snapshot_id": "a"})
    )
    observed(journal, SECOND, snapshot="a")
    raised(journal, SECOND, again)
    response = publish.execute(
        request(again, run=SECOND).model_copy(update={"snapshot_id": "a"})
    )

    assert response.resolved == ()
    assert response.status == NOTHING_NEW


def test_a_rewritten_passage_withdraws_and_is_thanked_for() -> None:
    journal = QueryableJournal()
    texts = Submissions(
        a=says("Adds a seamless poller."), b=says("Adds a poller.")
    )
    publish = publisher(journal=journal, enabled=True, submissions=texts)
    flagged = quoting("seamless poller")
    observed(journal, RUN, snapshot="a")
    raised(journal, RUN, flagged)
    publish.execute(
        request(flagged, run=RUN).model_copy(update={"snapshot_id": "a"})
    )
    observed(journal, SECOND, snapshot="b")
    response = publish.execute(
        request(run=SECOND).model_copy(update={"snapshot_id": "b"})
    )

    assert response.carried == ()
    assert "fixed since the last review" in response.comment


def test_a_new_corpus_withdraws_a_standing_finding_without_a_word() -> None:
    journal = QueryableJournal()
    texts = Submissions(a=says("Adds a seamless poller."))
    publish = publisher(journal=journal, enabled=True, submissions=texts)
    flagged = quoting("seamless poller")
    observed(journal, RUN, snapshot="a")
    raised(journal, RUN, flagged)
    publish.execute(
        request(flagged, run=RUN).model_copy(update={"snapshot_id": "a"})
    )
    observed(journal, SECOND, corpus="ffffffffffff", snapshot="a")
    response = publish.execute(
        request(run=SECOND).model_copy(
            update={"snapshot_id": "a", "corpus_version": "ffffffffffff"}
        )
    )

    assert response.carried == ()
    assert "fixed" not in response.comment


def test_a_finding_that_quotes_nothing_is_withdrawn_by_silence() -> None:
    journal = QueryableJournal()
    texts = Submissions(a=says("Adds a poller."))
    publish = publisher(journal=journal, enabled=True, submissions=texts)
    checked = finding("warn", "long line")
    observed(journal, RUN, snapshot="a")
    raised(journal, RUN, checked)
    publish.execute(
        request(checked, run=RUN).model_copy(update={"snapshot_id": "a"})
    )
    observed(journal, SECOND, snapshot="a")
    response = publish.execute(
        request(run=SECOND).model_copy(update={"snapshot_id": "a"})
    )

    assert response.carried == ()
    assert "fixed since the last review" in response.comment
