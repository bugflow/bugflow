"""Tests of ``JudgePullRequestUseCase``: each policy is judged and
recorded by itself, and each finding says where it came from."""

from datetime import timedelta

import pytest

from bugflow.review.domain.errors import (
    JudgeTemporarilyUnavailableError,
    JudgeUnavailableError,
)
from bugflow.review.domain.facts import (
    FINDING_RAISED,
    JUDGE_INVOKED,
    LLM_CALLED,
)
from bugflow.review.domain.models.corpus import Corpus
from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.judge_assessment import JudgeAssessment
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.review.domain.models.submission import Submission
from bugflow.review.dtos.judge_pull_request import (
    JudgePullRequestRequest,
    JudgePullRequestResponse,
)
from bugflow.review.infrastructure.in_memory_judge_archive import (
    InMemoryJudgeArchive,
)
from bugflow.review.infrastructure.stub_judge import StubJudge
from bugflow.review.tests.doubles import NOW, FixedClock, InMemorySubmissions
from bugflow.review.tests.journal import QueryableJournal
from bugflow.review.usecases.judge_pull_request import JudgePullRequestUseCase
from bugflow.shared.domain.models.call_record import CallRecord
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.digest import content_hash
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="orchard", repo="pear-tree", number=5)
RUN = Correlation(workflow_id="pr/5", run_id="run-1")
SUBMISSION = Submission(
    title="Add the poller and rename the command",
    body="Two changes.",
    commits=(),
    files=(),
)
DOCTRINE = DoctrineText(text="**RULE-1.** One change in a pull request.")
CLAUSES = {"P-01": "RULE-6", "Q-01": "RULE-4"}


def call(call_id: str, status: str = "ok") -> CallRecord:
    return CallRecord(
        call_id=call_id,
        purpose="judge",
        status=status,  # type: ignore[arg-type]
        requested_model="small",
        started_at=NOW,
        ended_at=NOW,
        client_duration_ms=1.0,
    )


class TwoPolicyJudge:
    """A judge with two policies. It raises one finding for each, unless
    told to refuse one or to be busy for one."""

    model_id = "a-model"
    fingerprint = "two-policies"
    policies = ("P-01", "Q-01")

    def __init__(self, refuse: str = "", busy: str = "") -> None:
        self.refuse = refuse
        self.busy = busy
        self.asked: list[str] = []

    def assess(
        self, submission: Submission, doctrine: DoctrineText, policy_id: str
    ) -> JudgeAssessment:
        self.asked.append(policy_id)
        if policy_id == self.refuse:
            raise JudgeUnavailableError(
                "the model declined", calls=(call("c-refused", "refused"),)
            )
        if policy_id == self.busy:
            raise JudgeTemporarilyUnavailableError(
                "rate limited", retry_after=timedelta(seconds=30)
            )
        return JudgeAssessment(
            findings=(
                Finding(
                    policy_id=policy_id,
                    severity="warn",
                    clause=CLAUSES[policy_id],
                    subject="pull request",
                    message=f"breaks {CLAUSES[policy_id]}",
                    judged_by="a-model",
                ),
            ),
            model="a-model",
            unsupported=("RULE-9: words nobody wrote",),
            exchange=JudgeExchange(
                request={"policy": policy_id}, response={"ok": True}
            ),
            input_tokens=10,
            output_tokens=1,
            calls=(call(f"c-{policy_id}"),),
        )


class Judged:
    """Runs the use case once and keeps what it used."""

    def __init__(
        self,
        judge: TwoPolicyJudge | StubJudge | None,
        corpus: Corpus | None = None,
        archive: InMemoryJudgeArchive | None = None,
        **request: object,
    ) -> None:
        self.journal = QueryableJournal()
        self.submissions = InMemorySubmissions()
        self.archive = archive
        self.snapshot = self.submissions.put(REF, SUBMISSION)
        self.corpus = corpus or Corpus(doctrine=DOCTRINE, judge="j1")
        self.response: JudgePullRequestResponse = JudgePullRequestUseCase(
            judge, self.submissions, self.journal, FixedClock(), archive
        ).execute(
            JudgePullRequestRequest(
                snapshot=self.snapshot,
                corpus=self.corpus,
                correlation=RUN,
                **request,  # type: ignore[arg-type]
            )
        )

    def entries(self, event_type: str) -> list[JournalEntry]:
        return [e for e in self.journal.entries if e.event_type == event_type]


def test_every_policy_is_judged_and_recorded_by_itself() -> None:
    judge = TwoPolicyJudge()
    judged = Judged(judge, head_sha="c" * 40)

    assert judge.asked == ["P-01", "Q-01"]
    assert [f.policy_id for f in judged.response.findings] == ["P-01", "Q-01"]
    assert judged.response.answered == ("P-01", "Q-01")
    assert judged.response.unavailable == ()
    assert judged.response.status == (
        "P-01 judged by a-model; Q-01 judged by a-model"
    )
    invoked = judged.entries(JUDGE_INVOKED)
    assert [e.payload["policy_id"] for e in invoked] == ["P-01", "Q-01"]
    first = invoked[0]
    assert first.commit_sha == "c" * 40
    assert first.payload["finding_count"] == 1
    assert first.payload["unsupported"] == ["RULE-9: words nobody wrote"]
    assert (first.payload["input_tokens"], first.payload["output_tokens"]) == (
        10,
        1,
    )
    assert len(judged.entries(FINDING_RAISED)) == 2


def test_a_named_policy_is_the_only_one_judged() -> None:
    judge = TwoPolicyJudge()
    judged = Judged(judge, policy_id="Q-01")

    assert judge.asked == ["Q-01"]
    assert judged.response.status == "judged by a-model"
    assert judged.response.answered == ("Q-01",)


def test_a_policy_the_judge_refuses_is_unavailable_and_others_go_on() -> None:
    judged = Judged(TwoPolicyJudge(refuse="P-01"))

    assert judged.response.unavailable == ("P-01",)
    assert judged.response.answered == ("Q-01",)
    assert [f.policy_id for f in judged.response.findings] == ["Q-01"]
    refused = judged.entries(JUDGE_INVOKED)[0]
    assert refused.payload["status"] == "unavailable: the model declined"
    assert refused.payload["identity"] is None


def test_every_call_to_the_model_is_recorded_even_a_refused_one() -> None:
    judged = Judged(TwoPolicyJudge(refuse="P-01"))

    calls = judged.entries(LLM_CALLED)
    assert [e.payload["call_id"] for e in calls] == ["c-refused", "c-Q-01"]
    assert calls[0].payload["status"] == "refused"
    assert calls[0].payload["started_at"] == NOW.isoformat().replace(
        "+00:00", "Z"
    )


def test_a_busy_judge_raises_while_the_caller_will_try_again() -> None:
    journal = QueryableJournal()
    submissions = InMemorySubmissions()
    use_case = JudgePullRequestUseCase(
        TwoPolicyJudge(busy="P-01"), submissions, journal, FixedClock()
    )
    request = JudgePullRequestRequest(
        snapshot=submissions.put(REF, SUBMISSION),
        corpus=Corpus(doctrine=DOCTRINE, judge="j1"),
        correlation=RUN,
        final_attempt=False,
    )

    with pytest.raises(JudgeTemporarilyUnavailableError) as raised:
        use_case.execute(request)

    assert raised.value.retry_after == timedelta(seconds=30)
    assert journal.entries == []


def test_a_busy_judge_on_the_final_attempt_is_recorded() -> None:
    judged = Judged(TwoPolicyJudge(busy="P-01"))

    assert judged.response.unavailable == ("P-01",)
    assert judged.entries(JUDGE_INVOKED)[0].payload["status"] == (
        "unavailable after retries: rate limited"
    )


def test_a_finding_says_which_judgement_it_came_from() -> None:
    archive = InMemoryJudgeArchive()
    judged = Judged(TwoPolicyJudge(), archive=archive, policy_id="P-01")

    (finding,) = judged.response.findings
    identity = finding.judge
    assert identity is not None
    assert identity.model == "a-model"
    assert identity.fingerprint == "two-policies"
    assert identity.input_hash == judged.snapshot.snapshot_id
    assert identity.prompt_hash == content_hash({"policy": "P-01"})
    assert identity.exchange_id is not None
    assert archive.get(identity.exchange_id).request == {"policy": "P-01"}
    recorded = judged.entries(JUDGE_INVOKED)[0].payload["identity"]
    assert recorded["exchange_id"] == identity.exchange_id


def test_with_nowhere_to_store_it_the_exchange_has_no_id() -> None:
    judged = Judged(TwoPolicyJudge(), policy_id="P-01")

    (finding,) = judged.response.findings
    assert finding.judge is not None
    assert finding.judge.exchange_id is None
    assert finding.judge.prompt_hash is not None


def test_a_finding_is_recorded_under_the_reviewer_it_belongs_to() -> None:
    corpus = Corpus(
        doctrine=DOCTRINE,
        judge="j1",
        installed={"prose": "prose-3"},
        reporting_agent="prose",
    )
    judged = Judged(TwoPolicyJudge(), corpus=corpus, policy_id="P-01")

    (finding,) = judged.response.findings
    assert (finding.agent_id, finding.corpus_version) == ("prose", "prose-3")
    (raised,) = judged.entries(FINDING_RAISED)
    assert (raised.agent_id, raised.corpus_version) == ("prose", "prose-3")
    (invoked,) = judged.entries(JUDGE_INVOKED)
    assert invoked.corpus_version == corpus.version
    assert invoked.agent_id is None


def test_with_no_reviewer_a_finding_has_the_evaluations_version() -> None:
    judged = Judged(TwoPolicyJudge(), policy_id="P-01")

    (finding,) = judged.response.findings
    assert finding.agent_id is None
    assert finding.corpus_version == judged.corpus.version


@pytest.mark.parametrize(
    "judge,use_judge,status",
    [
        (TwoPolicyJudge(), False, "skipped: judging disabled for this run"),
        (None, True, "skipped: no judge configured"),
    ],
)
def test_skipped_judging_is_recorded_and_reads_no_submission(
    judge: TwoPolicyJudge | None, use_judge: bool, status: str
) -> None:
    judged = Judged(judge, use_judge=use_judge)

    assert judged.response.status == status
    assert judged.response.findings == ()
    assert judged.response.answered == ()
    (invoked,) = judged.entries(JUDGE_INVOKED)
    assert invoked.payload["policy_id"] is None
    assert judged.submissions.read == 0


def test_the_stub_judge_finds_nothing_and_stores_an_exchange() -> None:
    archive = InMemoryJudgeArchive()
    judged = Judged(StubJudge(), archive=archive)

    assert judged.response.findings == ()
    assert judged.response.status == "judged by stub"
    assert judged.response.answered == ("stub",)
    (exchange,) = archive.exchanges.values()
    assert exchange.request["snapshot"] == SUBMISSION.content_id
    assert exchange.request["doctrine_version"] == DOCTRINE.version
    assert len(StubJudge().fingerprint) == 12
