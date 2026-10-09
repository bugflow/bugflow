"""Ask the judge about a pull request's policies, and record what it
said.

The judge is asked about one policy in each request. A caller that
names a policy has that one judged. A workflow does this, with one step
for each policy. A caller that names none has every policy the judge has
judged, one after another.

For each policy a "judge invoked" fact is recorded: which policy, how
it went, the tokens used, and what identifies the judgement. Each
finding carries the same identity: the model that answered, the judge's
fingerprint, a hash of the request, the submission judged, and where
the exchange is stored. The request and the response are stored, not
just the verdict, so that a judgement can be run again and examined
later.
"""

from dataclasses import asdict, dataclass, field, replace

from bugflow.review.domain.errors import (
    JudgeTemporarilyUnavailableError,
    JudgeUnavailableError,
)
from bugflow.review.domain.facts import JUDGE_INVOKED, LLM_CALLED
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.judge_assessment import JudgeAssessment
from bugflow.review.domain.models.judgement import JudgeIdentity
from bugflow.review.domain.models.recorder import Recorder
from bugflow.review.domain.models.submission import Submission, SubmissionRef
from bugflow.review.domain.repositories.judge_archive import (
    JudgeArchiveRepository,
)
from bugflow.review.domain.repositories.submission_source import (
    SubmissionSourceRepository,
)
from bugflow.review.domain.services.judge import JudgeService
from bugflow.review.dtos.judge_pull_request import (
    JudgePullRequestRequest,
    JudgePullRequestResponse,
)
from bugflow.review.usecases.model_calls import CALL_PAYLOAD, call_key
from bugflow.shared.domain.models.call_record import CallRecord
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.domain.values.digest import content_hash


def identity_of(
    assessment: JudgeAssessment,
    fingerprint: str,
    snapshot: SubmissionRef,
    archive: JudgeArchiveRepository | None,
) -> JudgeIdentity:
    """Build the identity of a judgement. If the judgement has an
    exchange and there is somewhere to store it, the exchange is
    stored."""
    exchange = assessment.exchange
    return JudgeIdentity(
        model=assessment.model,
        fingerprint=fingerprint,
        prompt_hash=content_hash(exchange.request) if exchange else None,
        input_hash=snapshot.snapshot_id,
        exchange_id=archive.put(exchange) if exchange and archive else None,
    )


@dataclass
class _Judgement:
    """How judging one policy went. ``policy_id`` is None when judging
    was skipped altogether."""

    policy_id: str | None
    status: str
    model: str | None = None
    findings: list[Finding] = field(default_factory=list)
    identity: JudgeIdentity | None = None
    unsupported: tuple[str, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0
    # Every call made to the model, including calls that failed.
    calls: tuple[CallRecord, ...] = ()


class JudgePullRequestUseCase:
    def __init__(
        self,
        judge: JudgeService | None,
        submissions: SubmissionSourceRepository,
        journal: RecordingService,
        clock: ClockService,
        archive: JudgeArchiveRepository | None = None,
    ) -> None:
        """``judge`` is None on a server with no judge set up. ``archive``
        is where exchanges are stored, or None to store none."""
        self._judge = judge
        self._submissions = submissions
        self._journal = journal
        self._clock = clock
        self._archive = archive

    def execute(
        self, request: JudgePullRequestRequest
    ) -> JudgePullRequestResponse:
        """Judge, record, and return the findings.

        If the judge is unavailable for now and the request is not the
        final attempt, ``JudgeTemporarilyUnavailableError`` is raised
        and nothing is recorded.
        """
        judgements: list[_Judgement] = []
        if not request.use_judge:
            judgements.append(
                _Judgement(None, "skipped: judging disabled for this run")
            )
        elif self._judge is None:
            judgements.append(_Judgement(None, "skipped: no judge configured"))
        elif not self._judge.policies:
            judgements.append(
                _Judgement(None, "skipped: the judge has no policies")
            )
        else:
            # The submission is read only if something will be judged.
            submission = self._submissions.get(request.snapshot)
            policies = (
                (request.policy_id,)
                if request.policy_id is not None
                else self._judge.policies
            )
            judgements = [
                self._judge_policy(request, self._judge, submission, policy_id)
                for policy_id in policies
            ]

        # A finding is recorded under the reviewer whose policy it is,
        # and that reviewer's corpus version. The "judge invoked" fact
        # is recorded under the evaluation's own corpus version, which
        # is what shows later that this commit has been judged.
        agent_id = request.corpus.reporting_agent
        version = request.corpus.version_for(agent_id)
        findings = [
            replace(f, corpus_version=version, agent_id=agent_id or None)
            for judgement in judgements
            for f in judgement.findings
        ]
        recorder = Recorder(
            request.snapshot.ref,
            request.correlation,
            request.corpus.version,
            self._clock.now(),
        )
        self._journal.append(
            [
                *(
                    recorder.entry(
                        LLM_CALLED,
                        call_key(call),
                        CALL_PAYLOAD.dump_python(call, mode="json"),
                    )
                    for j in judgements
                    for call in j.calls
                ),
                *(
                    recorder.entry(
                        JUDGE_INVOKED,
                        f"judge/{j.policy_id}" if j.policy_id else "judge",
                        commit_sha=request.head_sha,
                        payload={
                            "policy_id": j.policy_id,
                            "status": j.status,
                            "model": j.model,
                            "finding_count": len(j.findings),
                            "unsupported": list(j.unsupported),
                            "input_tokens": j.input_tokens,
                            "output_tokens": j.output_tokens,
                            "identity": (
                                asdict(j.identity) if j.identity else None
                            ),
                        },
                    )
                    for j in judgements
                ),
                *recorder.findings("judged", findings),
            ]
        )
        status = (
            judgements[0].status
            if len(judgements) == 1
            else "; ".join(f"{j.policy_id} {j.status}" for j in judgements)
        )
        return JudgePullRequestResponse(
            findings=tuple(findings),
            status=status,
            unavailable=tuple(
                j.policy_id
                for j in judgements
                if j.policy_id is not None
                and j.status.startswith("unavailable")
            ),
            answered=tuple(
                j.policy_id
                for j in judgements
                if j.policy_id is not None and j.status.startswith("judged by")
            ),
        )

    def _judge_policy(
        self,
        request: JudgePullRequestRequest,
        judge: JudgeService,
        submission: Submission,
        policy_id: str,
    ) -> _Judgement:
        """Ask the judge about one policy and return how it went."""
        try:
            assessment = judge.assess(
                submission, request.corpus.doctrine, policy_id
            )
        except JudgeTemporarilyUnavailableError as exc:
            if not request.final_attempt:
                raise
            return _Judgement(
                policy_id,
                f"unavailable after retries: {exc}",
                judge.model_id,
                calls=exc.calls,
            )
        except JudgeUnavailableError as exc:
            return _Judgement(
                policy_id,
                f"unavailable: {exc}",
                judge.model_id,
                calls=exc.calls,
            )
        identity = identity_of(
            assessment, judge.fingerprint, request.snapshot, self._archive
        )
        return _Judgement(
            policy_id=policy_id,
            status=f"judged by {assessment.model}",
            model=assessment.model,
            findings=[replace(f, judge=identity) for f in assessment.findings],
            identity=identity,
            unsupported=assessment.unsupported,
            input_tokens=assessment.input_tokens,
            output_tokens=assessment.output_tokens,
            calls=assessment.calls,
        )
