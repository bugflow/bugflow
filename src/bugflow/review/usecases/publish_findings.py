"""Publish what an evaluation found to the pull request, and record
what was done.

What is written to the forge:

- One comment, which has a part for each reviewer that has something to
  say. A comment is added and never edited or deleted.
- One commit status for each reviewer, on the pull request's last
  commit, named by the reviewer's agent id. A repository's branch rules
  can require it.
- One label, from a fixed set of three, that says what the review as a
  whole says.

Whether anything is written is decided for each repository by its
enforcement. If publishing is off, the response still has the text that
would have been posted.

When a reviewer speaks. A reviewer's first comment on a pull request is
always posted, even if it found nothing. After that it speaks only when
what it has to say changes: it raises something new, or something it
raised is gone. An evaluation that finds what the last one found posts
no comment.

Which findings count:

- A finding of a policy that somebody dismissed on the pull request is
  left out of everything: the label, what is new, and what is fixed.
- A warning that was chosen to be kept out of the pull request is left
  out the same way, and a "finding withheld" fact is recorded.
- A finding that quotes words stands for as long as those words are in
  the pull request and the corpus is the one that raised it. It is
  counted and shown even if this evaluation did not raise it again.
  Such a finding is called carried here. It goes when the words
  change, when its policy is dismissed, or when an evaluation under a
  new corpus does not raise it.
- A finding that quotes nothing goes when an evaluation whose policy
  answered does not raise it.
- Only a policy that answered can withdraw a finding. A policy that
  did not run raised nothing, and that says nothing about whether the
  author fixed anything.

An "action taken" fact is recorded for each reviewer's comment and
status and for the label. Each says whether the write was made, and if
not, why.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.errors import (
    PublicationRejectedError,
    SubmissionNotFoundError,
)
from bugflow.review.domain.facts import (
    ACTION_TAKEN,
    FINDING_DISMISSED,
    FINDING_RAISED,
    FINDING_REWRITTEN,
    PR_OBSERVED,
)
from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.enforcement import Enforcement, fails
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.recorder import Recorder
from bugflow.review.domain.models.review import (
    ReviewNote,
    ReviewStatus,
    ReviewVerdict,
    project,
)
from bugflow.review.domain.models.submission import SubmissionRef
from bugflow.review.domain.repositories.submission_source import (
    SubmissionSourceRepository,
)
from bugflow.review.domain.services.enforcement import EnforcementService
from bugflow.review.domain.services.governance import GovernanceService
from bugflow.review.domain.services.journal import JournalService
from bugflow.review.domain.services.publication import (
    CommitState,
    PublicationService,
)
from bugflow.review.domain.values.commentary import Seen, worth_saying
from bugflow.review.domain.values.passage import (
    passages,
    quoted,
    same_passage,
    stands,
)
from bugflow.review.domain.values.review_comments import (
    agent_comment,
    clean_comment,
    findings_comment,
)
from bugflow.review.domain.values.withholding import drawn
from bugflow.review.dtos.publish_findings import (
    PublishFindingsRequest,
    PublishFindingsResponse,
)
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.dismissal import Dismissal
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

#: Each comment starts with a hidden marker that holds the workflow
#: run's id. A step that is tried again after its answer was lost finds
#: the comment it already posted by this marker, and posts nothing.
MARKER_PREFIX = "<!-- bugflow:evaluation:"


def marker_for(correlation: Correlation, agent_id: str) -> str:
    """The hidden marker for one reviewer's part of one evaluation's
    comment.
    """
    return f"{MARKER_PREFIX}{correlation.run_id}:{agent_id} -->"


#: The three labels this use case sets and removes. It leaves every
#: other label alone.
MANAGED_LABELS = frozenset(("review:wip", "review:pass", "review:escalate"))
#: Statuses for an evaluation that wrote nothing: publishing is off for
#: the repository, the request asked for no publishing, or there was
#: nothing new to say.
DISABLED = "skipped: publishing disabled"
NOT_REQUESTED = "skipped: not published for this evaluation"
NOTHING_NEW = "skipped: nothing the last evaluation did not say"


def verdict_for(
    agent_id: str,
    policies: Sequence[str],
    head_sha: str,
    findings: Sequence[Finding],
    unavailable: Sequence[str] = (),
) -> ReviewVerdict | None:
    """Work out one reviewer's verdict on a commit from the findings of
    its policies. Returns None if it has none.

    - A reviewer with no policies has no verdict here. A checkout agent
      is one: its verdict comes from grading its write-up.
    - A finding of severity "fail" gives "fail", whatever else could
      not be answered.
    - Otherwise, if any of its policies could not be answered, it has
      no verdict: it has not reviewed the whole commit.
    - Otherwise "warn" if there is a warning, and "pass" if not.
    """
    if not policies:
        return None
    mine = set(policies)
    severities = {f.severity for f in findings if f.policy_id in mine}
    if "fail" in severities:
        return ReviewVerdict(
            agent_id=agent_id, head_sha=head_sha, status="fail"
        )
    if mine & set(unavailable):
        return None
    status: ReviewStatus = "warn" if "warn" in severities else "pass"
    return ReviewVerdict(agent_id=agent_id, head_sha=head_sha, status=status)


def review_label(
    head_sha: str | None,
    agents: Mapping[str, Sequence[str]],
    governing: Iterable[str],
    findings: Sequence[Finding],
    unavailable: Sequence[str] = (),
    reported: Sequence[ReviewVerdict] = (),
) -> str:
    """Work out the label for the pull request.

    ``agents`` gives each reviewer's policies. ``reported`` are
    verdicts that reviewers gave directly, as checkout agents do; such
    a reviewer's verdict is not worked out from findings as well.

    With no last commit to attach a verdict to, the label is
    "review:wip".
    """
    if head_sha is None:
        return "review:wip"
    verdicts = [
        verdict
        for agent_id, policies in agents.items()
        if (
            verdict := verdict_for(
                agent_id, policies, head_sha, findings, unavailable
            )
        )
        is not None
    ]
    reported_by = {verdict.agent_id for verdict in reported}
    verdicts = [v for v in verdicts if v.agent_id not in reported_by]
    return project(head_sha, governing, [*verdicts, *reported])


def _count(n: int, noun: str) -> str:
    """A number and a noun, made plural if the number is not one."""
    return f"{n} {noun}{'' if n == 1 else 's'}"


def commit_status_for(
    findings: Sequence[Finding], unavailable: Sequence[str] = ()
) -> tuple[CommitState, str]:
    """The state and the text of a reviewer's commit status.

    Only a finding of severity "fail" fails the status. Warnings do
    not. A policy that could not be answered does not fail it either,
    because that is a fault of the server and not of the pull request;
    the text names the policies that went unanswered.
    """
    fails = sum(1 for f in findings if f.severity == "fail")
    warns = sum(1 for f in findings if f.severity == "warn")
    n = len(unavailable)
    unanswered = (
        f"; {n} polic{'y' if n == 1 else 'ies'} unanswered "
        f"({', '.join(sorted(unavailable))})"
        if unavailable
        else ""
    )
    if fails:
        also = f", {_count(warns, 'warning')}" if warns else ""
        return (
            "failure",
            f"{_count(fails, 'failing finding')}{also}{unanswered}",
        )
    if warns:
        return "success", f"{_count(warns, 'warning')}; advisory{unanswered}"
    if unavailable:
        return "success", f"nothing assessed{unanswered}"
    return "success", "no findings"


def _identity(finding: Finding) -> tuple[str, str, str]:
    """What identifies a finding: its policy, clause and subject.

    The message is left out, because it may quote a count that changes
    while the problem stays. The clause is included, because one
    passage can break two clauses of one policy.
    """
    return (finding.policy_id, finding.clause, finding.subject)


def resolved_since(
    previous: Sequence[Finding],
    current: Sequence[Finding],
    answered: Collection[str],
) -> tuple[Finding, ...]:
    """The findings the previous evaluation raised that this one
    withdraws.

    ``answered`` are the policies that answered in this evaluation.
    Only their findings can be withdrawn.
    """
    assessed = set(answered)
    resolved: dict[tuple[str, str, str], Finding] = {}
    for f in previous:
        if f.policy_id in assessed and not any(
            same_passage(f, c) for c in current
        ):
            resolved.setdefault(_identity(f), f)
    return tuple(resolved.values())


def cited_clauses(
    doctrine: DoctrineText, findings: Sequence[Finding]
) -> dict[str, str]:
    """The text of each clause the findings cite, by clause id. A clause
    the doctrine does not have is left out.
    """
    cited = {}
    for clause in dict.fromkeys(f.clause for f in findings):
        text = doctrine.clause(clause)
        if text is not None:
            cited[clause] = text
    return cited


#: What a reviewer that judges or checks says in its first comment
#: when it found nothing.
READ = (
    "The title, the description and the commit messages were read against "
    "the doctrine, and nothing in them breaks it."
)

# A checkout agent's commit status and its text, for each verdict.
_AGENT_STATUS: dict[ReviewStatus, tuple[CommitState, str]] = {
    "pass": ("success", "nothing to raise"),
    "warn": ("success", "something to consider"),
    "fail": ("failure", "a problem to fix"),
}


class _Said(BaseModel):
    """One reviewer's part of an evaluation: the text of its comment,
    its commit status, and counts of its findings. ``body`` is empty if
    the reviewer has nothing to say. ``state`` is None if it has no
    verdict.
    """

    model_config = ConfigDict(frozen=True)

    agent_id: str
    body: str
    state: CommitState | None
    description: str
    verdict: ReviewStatus | None = None
    raised: int = 0
    fixed: int = 0
    findings: int = 0
    dismissed: int = 0


def _enforced(
    state: CommitState,
    description: str,
    verdict: str | None,
    governs: bool,
    enforcement: Enforcement,
) -> tuple[CommitState, str]:
    """Apply the repository's enforcement to a commit status.

    A status fails only for a reviewer that governs the repository,
    and only if the enforcement fails at this verdict. Otherwise a
    status that would have failed is set to success and marked
    "advisory".
    """
    if governs and fails(enforcement, verdict):
        return "failure", description
    if state == "failure" or (governs and verdict == "warn"):
        return "success", f"{description}; advisory"
    return state, description


class PublishFindingsUseCase:
    def __init__(
        self,
        forge: PublicationService,
        journal: JournalService,
        clock: ClockService,
        enforcement: EnforcementService,
        agents: Mapping[str, tuple[str, ...]] | None = None,
        governance: GovernanceService | None = None,
        summaries: Mapping[str, str] | None = None,
        submissions: SubmissionSourceRepository | None = None,
    ) -> None:
        """``forge`` writes to the pull request. ``enforcement`` says what
        may be published for a repository. ``agents`` gives the policies
        of each installed reviewer, by agent id. ``governance`` says
        which reviewers decide a repository's label; with none, no
        reviewer does. ``summaries`` gives each policy's one-sentence
        summary, which a comment uses to name a rule. ``submissions``
        reads back the text of the pull request, so that a finding raised
        earlier can be checked against it; with none, no finding is
        carried and none is recorded as rewritten.
        """
        self._forge = forge
        self._journal = journal
        self._clock = clock
        self._submissions = submissions
        self._enforcement = enforcement
        self._agents = dict(agents or {})
        self._governance = governance
        self._summaries = dict(summaries or {})

    def _governing_for(self, ref: PullRequestRef) -> frozenset[str]:
        """The reviewers that decide this repository's label."""
        if self._governance is None:
            return frozenset()
        return self._governance.governing_agents(
            ref.forge, f"{ref.owner}/{ref.repo}"
        )

    def _owner(self, finding: Finding) -> str:
        """The reviewer whose comment shows a finding: the one whose policy
        it is. If no installed reviewer has the policy, it is the first
        reviewer that has any policy, so that the finding is still shown.
        """
        for agent_id, policies in self._agents.items():
            if finding.policy_id in policies:
                return agent_id
        declaring = [a for a, p in self._agents.items() if p]
        return declaring[0] if declaring else "doctrine"

    def _text(self, request: PublishFindingsRequest) -> str | None:
        """Everything the pull request says that a policy may quote, as
        this evaluation read it. None if it cannot be read back.
        """
        if self._submissions is None or request.snapshot_id is None:
            return None
        try:
            submission = self._submissions.get(
                SubmissionRef(snapshot_id=request.snapshot_id, ref=request.ref)
            )
        except SubmissionNotFoundError:
            return None
        return passages(submission)

    def _carried(
        self,
        request: PublishFindingsRequest,
        current: Sequence[Finding],
        text: str | None,
        dismissed_policies: Collection[str],
        kept_back: Collection[tuple[str, str, str]],
    ) -> list[Finding]:
        """The findings that stand although this evaluation did not raise
        them.

        It takes the latest record of every finding ever raised on the
        pull request, and keeps one if all of these hold: it quotes words
        that are still in the text; the evaluation that raised it ran
        under the present corpus version; its policy is not dismissed and
        it is not kept out; and nothing in ``current`` is the same
        finding.
        """
        if text is None:
            return []
        corpus_of_run = {
            e.run_id: e.corpus_version
            for e in self._journal.events_for_pull_request(
                request.ref, PR_OBSERVED
            )
        }
        latest: dict[tuple[str, str, str], tuple[str | None, Finding]] = {}
        for e in self._journal.events_for_pull_request(
            request.ref, FINDING_RAISED
        ):
            f = Finding.from_payload(e.payload)
            latest[_identity(f)] = (corpus_of_run.get(e.run_id), f)
        carried: list[Finding] = []
        for corpus, f in latest.values():
            if f.policy_id in dismissed_policies or _identity(f) in kept_back:
                continue
            if corpus != request.corpus_version or not quoted(f):
                continue
            if any(same_passage(f, c) for c in current):
                continue
            if any(same_passage(f, c) for c in carried):
                continue
            if stands(f, text):
                carried.append(f)
        return carried

    def _rewritten(
        self,
        request: PublishFindingsRequest,
        previous: Sequence[Finding],
        text: str | None,
    ) -> list[Finding]:
        """The earlier findings whose quoted words are no longer in the
        pull request, and for which that has not been recorded before.
        """
        if text is None:
            return []
        already = {
            _identity(Finding.from_payload(e.payload))
            for e in self._journal.events_for_pull_request(
                request.ref, FINDING_REWRITTEN
            )
        }
        gone: dict[tuple[str, str, str], Finding] = {}
        for f in previous:
            if _identity(f) in already or _identity(f) in gone:
                continue
            if stands(f, text) is False:
                gone[_identity(f)] = f
        return list(gone.values())

    def _previous_findings(
        self, request: PublishFindingsRequest
    ) -> tuple[Correlation | None, list[Finding]]:
        """The last evaluation before this one that published, and the
        findings it raised.
        """
        previous = self._journal.latest_acted_run(
            request.ref, excluding=request.correlation
        )
        if previous is None:
            return None, []
        return previous, [
            Finding.from_payload(e.payload)
            for e in self._journal.entries_for_run(previous)
            if e.event_type == FINDING_RAISED
        ]

    def _standing(
        self, request: PublishFindingsRequest
    ) -> set[tuple[str, str, str]]:
        """The findings that every evaluation of the present text raised,
        by identity.

        The entry for a finding does not say what text its evaluation
        read. The evaluation recorded that once, when it read the pull
        request: the id of the stored submission, or the commit if there
        is none. If no evaluation of this text has recorded a finding, or
        there is no last commit, this evaluation's own findings are
        returned.
        """
        if request.head_sha is None:
            return {_identity(f) for f in request.findings}
        read_by: dict[str, str] = {}
        for entry in self._journal.events_for_pull_request(
            request.ref, PR_OBSERVED
        ):
            snapshot = entry.payload.get("snapshot_id")
            read_by[entry.run_id] = (
                str(snapshot) if snapshot else entry.commit_sha or ""
            )
        here = read_by.setdefault(
            request.correlation.run_id,
            request.snapshot_id or request.head_sha,
        )
        history = [
            Seen(
                run_id=entry.run_id,
                read=read_by.get(entry.run_id) or "",
                finding=Finding.from_payload(entry.payload),
            )
            for entry in self._journal.events_for_pull_request(
                request.ref, FINDING_RAISED
            )
        ]
        if not any(seen.read == here for seen in history):
            return {_identity(f) for f in request.findings}
        return {_identity(f) for f in worth_saying(history, read=here)}

    def _observed(
        self, run: Correlation | None
    ) -> tuple[str | None, str | None]:
        """The submission an earlier evaluation read and the corpus version
        it ran under.
        """
        if run is None:
            return None, None
        for e in self._journal.entries_for_run(run):
            if e.event_type == PR_OBSERVED:
                return e.payload.get("snapshot_id"), e.corpus_version
        return None, None

    def _spoken(
        self, ref: PullRequestRef, agent_id: str
    ) -> list[dict[str, object]]:
        """The records of the comments this reviewer has had posted on the
        pull request, oldest first. A comment that was worked out and not
        posted does not count.
        """
        return [
            e.payload
            for e in self._journal.events_for_pull_request(ref, ACTION_TAKEN)
            if e.payload.get("action") == "review_comment"
            and e.payload.get("agent_id") == agent_id
            and e.payload.get("performed") is True
        ]

    def execute(
        self, request: PublishFindingsRequest
    ) -> PublishFindingsResponse:
        """Work out what to say, write it if publishing is on, and record
        what was done.
        """
        previous, previous_findings = self._previous_findings(request)
        resolved = resolved_since(
            previous_findings, request.findings, request.answered
        )
        dismissals = [
            Dismissal.from_payload(e.payload)
            for e in self._journal.events_for_pull_request(
                request.ref, FINDING_DISMISSED
            )
        ]
        dismissed_policies = {d.policy_id for d in dismissals}
        dismissed = tuple(
            f for f in request.findings if f.policy_id in dismissed_policies
        )
        governing = self._governing_for(request.ref)
        enforcement = self._enforcement.enforcement_for(
            request.ref.forge, f"{request.ref.owner}/{request.ref.repo}"
        )
        # Whether a warning is kept out depends only on the pull request
        # and the finding, so the same warnings are kept out at every
        # evaluation.
        withheld = tuple(
            f
            for f in request.findings
            if f.policy_id not in dismissed_policies
            and drawn(request.ref, f, enforcement.withholds)
        )
        kept_back = {_identity(f) for f in withheld}
        current = [
            f
            for f in request.findings
            if f.policy_id not in dismissed_policies
            and _identity(f) not in kept_back
        ]
        text = self._text(request)
        carried = self._carried(
            request, current, text, dismissed_policies, kept_back
        )
        counted = [*current, *carried]
        label = review_label(
            request.head_sha,
            self._agents,
            governing,
            counted,
            request.unavailable,
            request.verdicts,
        )
        removed = MANAGED_LABELS - {label}

        # What is new since the last evaluation that published, and
        # what is gone since it.
        stands = self._standing(request)
        previously = {_identity(f) for f in previous_findings}
        earlier = [*previous_findings, *carried]
        raised = tuple(
            f
            for f in current
            if not any(same_passage(f, e) for e in earlier)
            and _identity(f) in stands
        )
        still = {_identity(f) for f in carried}
        fixed = tuple(
            f
            for f in resolved
            if f.policy_id not in dismissed_policies
            and not drawn(request.ref, f, enforcement.withholds)
            and _identity(f) not in still
        )

        # The same text read again under a new corpus: the review
        # changed and the pull request did not.
        snapshot, corpus = self._observed(previous)
        rejudged = (
            request.snapshot_id is not None
            and snapshot == request.snapshot_id
            and corpus != request.corpus_version
        )
        said = [
            *self._findings_reviewers(
                request,
                counted,
                raised,
                fixed,
                dismissed,
                governing,
                enforcement,
                rejudged,
                spoken_of=stands | previously | still,
            ),
            *self._checkout_reviewers(request, governing, enforcement),
        ]

        enabled = enforcement.publishes and request.publish
        if enabled:
            status = "published"
        else:
            status = DISABLED if not enforcement.publishes else NOT_REQUESTED
        speaking = [one for one in said if one.body]
        comment_ids: dict[str, int] = {}
        if enabled and speaking:
            # The comment starts with the marker the forge matches on.
            # Each reviewer's part keeps its own marker inside it.
            marker = marker_for(request.correlation, "review")
            comment_id = self._forge.add_comment(
                request.ref,
                marker,
                "\n\n".join([marker, *(one.body for one in speaking)]),
            )
            comment_ids = {one.agent_id: comment_id for one in speaking}
        if enabled:
            self._forge.set_labels(
                request.ref, add=frozenset({label}), remove=removed
            )
        statuses = {
            one.agent_id: self._set_status(request, one, enabled, status)
            for one in said
        }

        recorder = Recorder(
            request.ref,
            request.correlation,
            request.corpus_version,
            self._clock.now(),
        )
        entries = [
            recorder.entry(
                ACTION_TAKEN,
                "outcome_label",
                {
                    "action": "outcome_label",
                    "performed": enabled,
                    "status": status,
                    "label": label,
                    "removed": sorted(removed),
                },
            )
        ]
        for one in said:
            entries += [
                recorder.entry(
                    ACTION_TAKEN,
                    f"review_comment/{one.agent_id}",
                    {
                        "action": "review_comment",
                        "agent_id": one.agent_id,
                        "performed": enabled and bool(one.body),
                        "status": status if one.body else NOTHING_NEW,
                        "comment_id": comment_ids.get(one.agent_id),
                        "verdict": one.verdict,
                        "head_sha": request.head_sha,
                        "finding_count": one.findings,
                        "raised_count": one.raised,
                        "fixed_count": one.fixed,
                        "dismissed_count": one.dismissed,
                    },
                ),
                recorder.entry(
                    ACTION_TAKEN,
                    f"commit_status/{one.agent_id}",
                    {
                        "action": "commit_status",
                        "agent_id": one.agent_id,
                        "performed": statuses[one.agent_id] == "published",
                        "status": statuses[one.agent_id],
                        "context": one.agent_id,
                        "state": one.state,
                        "description": one.description,
                    },
                    commit_sha=request.head_sha,
                ),
            ]
        if previous is not None:
            entries += recorder.resolutions(previous, resolved)
            entries += recorder.rewritten(
                previous,
                self._rewritten(request, [*previous_findings, *carried], text),
            )
        # A withheld warning is recorded once, at the evaluation where
        # it would first have been shown.
        entries += recorder.withheld(
            enforcement.withholds,
            [
                f
                for f in withheld
                if _identity(f) not in previously and _identity(f) in stands
            ],
        )
        self._journal.append(entries)

        bodies = [one.body for one in said if one.body]
        return PublishFindingsResponse(
            status=status if bodies else NOTHING_NEW,
            label=label,
            comment="\n".join(bodies),
            comments={one.agent_id: one.body for one in said if one.body},
            comment_id=next(iter(comment_ids.values()), None),
            resolved=resolved,
            dismissed=dismissed,
            withheld=withheld,
            carried=tuple(carried),
        )

    def _set_status(
        self,
        request: PublishFindingsRequest,
        one: _Said,
        enabled: bool,
        status: str,
    ) -> str:
        """Set one reviewer's commit status and return how it went.

        If the forge refuses, that is returned and not raised: the
        comment and the label have been written and stay.
        """
        if request.head_sha is None:
            return "skipped: no head commit"
        if one.state is None:
            return "skipped: no verdict"
        if not enabled:
            return status
        try:
            self._forge.set_commit_status(
                request.ref,
                request.head_sha,
                one.agent_id,
                one.state,
                one.description,
            )
        except PublicationRejectedError as exc:
            return f"rejected: {exc}"
        return "published"

    def _findings_reviewers(
        self,
        request: PublishFindingsRequest,
        counted: Sequence[Finding],
        raised: Sequence[Finding],
        fixed: Sequence[Finding],
        dismissed: Sequence[Finding],
        governing: frozenset[str],
        enforcement: Enforcement,
        rejudged: bool = False,
        spoken_of: Collection[tuple[str, str, str]] | None = None,
    ) -> list[_Said]:
        """What each reviewer that judges or checks has to say.

        ``counted`` are the findings that count, ``raised`` those that
        are new, ``fixed`` those that are gone. ``spoken_of`` are the
        identities of findings that may be counted in a comment: those
        every evaluation of this text raised, and those shown before.

        A reviewer's first comment has everything it holds against the
        last commit. Later comments have what is new and what is gone.
        If ``rejudged`` is set, a reviewer that has spoken before speaks
        only if its verdict changed, and then gives everything it holds.
        """
        owners = [a for a, p in self._agents.items() if p]
        for f in (*counted, *fixed):
            if self._owner(f) not in owners:
                owners.append(self._owner(f))
        said = []
        for agent_id in owners:
            policies = self._agents.get(agent_id, ())
            mine = [f for f in counted if self._owner(f) == agent_id]
            new = [f for f in raised if self._owner(f) == agent_id]
            gone = [f for f in fixed if self._owner(f) == agent_id]
            unanswered = sorted(set(request.unavailable) & set(policies))
            spoken = self._spoken(request.ref, agent_id)
            first = not spoken
            verdict = (
                verdict_for(
                    agent_id,
                    policies,
                    request.head_sha,
                    counted,
                    request.unavailable,
                )
                if request.head_sha
                else None
            )
            now = verdict.status if verdict else None
            marker = marker_for(request.correlation, agent_id)
            if first:
                new, gone = list(mine), []
            if rejudged and not first:
                moved = now != spoken[-1].get("verdict")
                new, gone = (list(mine), []) if moved else ([], [])
                body = (
                    findings_comment(
                        marker,
                        agent_id,
                        new,
                        [],
                        mine,
                        self._summaries,
                        request.clauses,
                        rejudged=True,
                    )
                    if moved
                    else ""
                )
            elif new or gone:
                said_of = (
                    mine
                    if spoken_of is None
                    else [f for f in mine if _identity(f) in spoken_of]
                )
                body = findings_comment(
                    marker,
                    agent_id,
                    new,
                    gone,
                    said_of,
                    self._summaries,
                    request.clauses,
                )
            elif first and not unanswered and request.head_sha:
                body = clean_comment(
                    marker,
                    agent_id,
                    READ,
                    [
                        self._summaries[p]
                        for p in policies
                        if p in self._summaries
                    ],
                )
            else:
                body = ""
            state, description = commit_status_for(mine, unanswered)
            state, description = _enforced(
                state,
                description,
                verdict.status if verdict else None,
                agent_id in governing,
                enforcement,
            )
            said.append(
                _Said(
                    agent_id=agent_id,
                    body=body,
                    state=state,
                    description=description,
                    verdict=verdict.status if verdict else None,
                    raised=len(new),
                    fixed=len(gone),
                    findings=len(mine),
                    dismissed=sum(
                        self._owner(f) == agent_id for f in dismissed
                    ),
                )
            )
        return said

    def _checkout_reviewers(
        self,
        request: PublishFindingsRequest,
        governing: frozenset[str],
        enforcement: Enforcement,
    ) -> list[_Said]:
        """What each checkout agent with a verdict on the last commit has
        to say.

        Its first verdict on a pull request is always shown. After that
        it speaks if its verdict changed, or if its verdict is not a pass
        and it has not spoken about this commit.
        """
        notes = {n.agent_id: n for n in request.notes}
        said = []
        for verdict in request.verdicts:
            if verdict.head_sha != request.head_sha:
                continue
            agent_id = verdict.agent_id
            spoken = self._spoken(request.ref, agent_id)
            last = spoken[-1] if spoken else None
            speaks = (
                last is None
                or last.get("verdict") != verdict.status
                or (
                    verdict.status != "pass"
                    and last.get("head_sha") != verdict.head_sha
                )
            )
            note = notes.get(agent_id) or ReviewNote(
                agent_id=agent_id, head_sha=verdict.head_sha
            )
            body = (
                agent_comment(
                    marker_for(request.correlation, agent_id),
                    verdict.status,
                    note,
                )
                if speaks
                else ""
            )
            state, description = _AGENT_STATUS[verdict.status]
            state, description = _enforced(
                state,
                description,
                verdict.status,
                agent_id in governing,
                enforcement,
            )
            said.append(
                _Said(
                    agent_id=agent_id,
                    body=body,
                    state=state,
                    description=description,
                    verdict=verdict.status,
                )
            )
        return said
