"""Run the em dash check on a pull request, and record what it found.

The check looks for dashes used as punctuation in the title and the
description. A function answers it. No model is called, so it has no
quota or rate limit and gives the same answer every time.

The server does not decide which policy this is. The request gives the
policy's id and the clause its findings cite, and both come from the
reviewer that chose the check.

Its findings are warnings. There is one for each dash, so that fixing
one dash settles the finding about it and leaves the others.

Each run records a "policy checked" fact, even when it finds nothing.
Without it, a policy that ran and found nothing could not be told from
one that never ran. The fact gives a small cost that is not zero, as
``checked_policy`` explains.

Commit messages are not checked here. A commit message cannot be edited
afterwards without rewriting history, so a rule about commit messages
belongs in a check that refuses the commit.
"""

from collections.abc import Sequence

from bugflow.review.domain.facts import POLICY_CHECKED
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.recorder import Recorder
from bugflow.review.domain.models.submission import Submission
from bugflow.review.domain.repositories.submission_source import (
    SubmissionSourceRepository,
)
from bugflow.review.domain.values.checked_policy import CHECKED_COST_USD
from bugflow.review.domain.values.passage import SUBJECT_QUOTE
from bugflow.review.dtos.check_pull_request import (
    CheckPullRequestRequest,
    CheckPullRequestResponse,
)
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.domain.values.typography import em_dashes


def em_dash_findings(
    submission: Submission,
    policy_id: str,
    clause: str,
    corpus_version: str,
    agent_id: str = "",
) -> tuple[Finding, ...]:
    """One warning for each dash in the title or the description.

    A finding's subject holds the start of the words around the dash,
    which is what tells one of these findings from another.
    """
    text = f"{submission.title}\n{submission.body}"
    return tuple(
        Finding(
            policy_id=policy_id,
            severity="warn",
            clause=clause,
            subject=f'description "{_cut(quote)}"',
            message=(
                f'"{quote}": an em dash stands here where a colon, a comma, '
                "a semicolon or a full stop belongs."
            ),
            corpus_version=corpus_version,
            agent_id=agent_id or None,
        )
        for quote in em_dashes(text)
    )


def _cut(quote: str) -> str:
    """The quotation, shortened to fit a finding's subject."""
    if len(quote) <= SUBJECT_QUOTE:
        return quote
    return quote[:SUBJECT_QUOTE].rstrip() + "..."


class CheckPullRequestUseCase:
    def __init__(
        self,
        submissions: SubmissionSourceRepository,
        journal: RecordingService,
        clock: ClockService,
    ) -> None:
        self._submissions = submissions
        self._journal = journal
        self._clock = clock

    def execute(
        self, request: CheckPullRequestRequest
    ) -> CheckPullRequestResponse:
        submission = self._submissions.get(request.snapshot)
        findings = em_dash_findings(
            submission,
            request.policy_id,
            request.clause,
            request.corpus_version,
            request.agent_id,
        )
        self._record(request, findings)
        return CheckPullRequestResponse(
            findings=findings,
            status=f"checked: {len(findings)} em dashes",
            answered=(request.policy_id,),
        )

    def _record(
        self,
        request: CheckPullRequestRequest,
        findings: Sequence[Finding],
    ) -> None:
        recorder = Recorder(
            request.snapshot.ref,
            request.correlation,
            request.corpus_version,
            self._clock.now(),
        )
        self._journal.append(
            [
                recorder.entry(
                    POLICY_CHECKED,
                    f"checked/{request.policy_id}",
                    {
                        "policy_id": request.policy_id,
                        "clause": request.clause,
                        "finding_count": len(findings),
                        "cost": {"usd": CHECKED_COST_USD},
                    },
                    agent_id=request.agent_id or None,
                ),
                *recorder.findings("checked", findings),
            ]
        )
