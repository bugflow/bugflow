"""Use case: observe a pull request.

It reads the pull request from the forge, stores the snapshot, finds out
which rules are in force, and records a ``pr.observed`` fact.

From then on, later steps are given a reference to the stored snapshot and
not the snapshot itself. That keeps what a workflow engine records between
steps small.
"""

from bugflow.forge.domain import facts
from bugflow.forge.domain.repositories.evaluation_regime import (
    EvaluationRegimeRepository,
)
from bugflow.forge.domain.repositories.snapshots import SnapshotStoreRepository
from bugflow.forge.domain.services.forge import ForgeService
from bugflow.forge.domain.services.journal_history import (
    PullRequestJournalService,
)
from bugflow.forge.domain.services.review_scope import ReviewScopeService
from bugflow.forge.dtos.observe_pull_request import (
    ObservePullRequestRequest,
    ObservePullRequestResponse,
)
from bugflow.shared.domain.models.recorder import Recorder
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class ObservePullRequestUseCase:
    """Takes a pull request. Returns a reference to its stored snapshot, a
    summary of it, the rules in force, and whether this content has already
    been reviewed.
    """

    def __init__(
        self,
        forge: ForgeService,
        corpus: EvaluationRegimeRepository,
        snapshots: SnapshotStoreRepository,
        journal: RecordingService,
        history: PullRequestJournalService,
        clock: ClockService,
        # The review scope is recorded so that a policy switched off for this
        # repository can be told apart from one that ran and found nothing. If
        # no scope service was given, nothing is recorded about scope.
        scope: ReviewScopeService | None = None,
    ) -> None:
        self._forge = forge
        self._corpus = corpus
        self._snapshots = snapshots
        self._journal = journal
        self._history = history
        self._clock = clock
        self._scope = scope

    def _scoped(self, ref: PullRequestRef) -> dict[str, list[str]]:
        if self._scope is None:
            return {}
        scope = self._scope.scope_for(ref.forge, f"{ref.owner}/{ref.repo}")
        return {
            "reviewed_for": list(scope.reviewed_for),
            "held": list(scope.held),
        }

    def execute(
        self, request: ObservePullRequestRequest
    ) -> ObservePullRequestResponse:
        snapshot = self._forge.fetch_snapshot(request.ref)
        reference = self._snapshots.put(snapshot)
        corpus = self._corpus.current()
        head = snapshot.commits[-1].sha if snapshot.commits else None
        recorder = Recorder(
            request.ref,
            request.correlation,
            corpus.version,
            self._clock.now(),
        )
        self._journal.append(
            [
                recorder.entry(
                    facts.PR_OBSERVED,
                    head or "no-commits",
                    {
                        # The most recent delivery, and all the deliveries this
                        # observation answers.
                        "delivery_id": (
                            request.delivery_ids[-1]
                            if request.delivery_ids
                            else None
                        ),
                        "delivery_ids": list(request.delivery_ids),
                        "snapshot_id": reference.snapshot_id,
                        "corpus": corpus.components,
                        # The version of every installed review agent, so that
                        # the full set of rules on the day can be looked up
                        # later.
                        "installed": dict(corpus.installed),
                        # The policies applied, and the policies that could
                        # have been. One in the second list and not the first
                        # was switched off for this repository.
                        **self._scoped(request.ref),
                        "title": snapshot.title,
                        "head_branch": snapshot.head_branch,
                        "base_branch": snapshot.base_branch,
                        "author_login": snapshot.author_login,
                        # Each commit's author and committer as git recorded
                        # them, and the account the forge matched to each.
                        # Recorded as plain facts. What they mean is for
                        # whoever analyses the journal.
                        "commits": [
                            {
                                "sha": c.sha,
                                "author_name": c.author.name,
                                "author_email": c.author.email,
                                "author_login": c.author.login,
                                "committer_name": c.committer.name,
                                "committer_email": c.committer.email,
                                "committer_login": c.committer.login,
                                "verified": c.verified,
                                "verification_reason": c.verification_reason,
                            }
                            for c in snapshot.commits
                        ],
                        "file_count": len(snapshot.files),
                        "changed_lines": snapshot.changed_lines,
                    },
                    commit_sha=head,
                )
            ]
        )
        return ObservePullRequestResponse(
            snapshot=reference,
            summary=snapshot.summary(),
            corpus=corpus,
            judged_before=self._judged_before(
                request.ref,
                reference.snapshot_id,
                corpus.version,
                frozenset(request.declared),
            ),
        )

    def _judged_before(
        self,
        ref: PullRequestRef,
        snapshot_id: str,
        version: str,
        declared: frozenset[str],
    ) -> bool:
        """Whether this content has already been reviewed under the rules in
        force.

        What counts as "this content" is the whole snapshot: title,
        description, commits and diffs. The commit alone is not enough,
        because a description can be edited without a new commit, and some
        policies read the description.

        The check is needed because the same change can arrive twice. A
        forge's webhook gives each delivery its own id, and the poller
        makes up another, so one push reported both ways is two deliveries.
        Without this check it would be reviewed twice.

        Only a review that produced an answer counts. One that failed, for
        example on a rate limit, leaves the work still to do.

        The answers are counted per policy. The content has been reviewed
        before only if every policy it would be reviewed against now
        already has an answer for it. So when a policy is added for a
        repository, content reviewed earlier is reviewed again for the new
        policy. If the request names no policies, the question is only
        whether anything reviewed this content at all.
        """
        answered = {
            entry.payload.get("policy_id")
            for entry in self._history.events_for_pull_request(
                ref, facts.JUDGE_INVOKED
            )
            if (entry.payload.get("identity") or {}).get("input_hash")
            == snapshot_id
            and entry.corpus_version == version
            and str(entry.payload.get("status", "")).startswith("judged by")
        }
        if not answered:
            return False
        return declared <= answered
