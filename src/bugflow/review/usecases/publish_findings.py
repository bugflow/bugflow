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

Whether anything is written is decided for each gnome on each
repository by its setting (ADR 008). A gnome at ``observe`` is judged
and recorded, and its part of the comment and its status are not
written. A gnome at ``advise`` or ``gate`` has both written, and the
label is written when any gnome publishes. If nothing publishes, the
response still has the text that would have been posted.

When a reviewer speaks. A reviewer that judges or checks speaks when it
has something to say: its first comment holds everything it found, and
after that it speaks only when what it has to say changes: it raises
something new, or something it raised is gone. A reviewer that found
nothing posts no comment, and its commit status says so. An evaluation
that finds what the last one found posts no comment.

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

With an editor, the comment the author reads is the editor's, written
from the draft of every part that would be posted. A "comment edited"
fact keeps the draft and what was posted, or why the draft was posted
as it was. The editor writes at observe too, where nothing is posted,
so the journal holds what it would have said. The editor may shorten
the draft, but its comment keeps the clause link of every failing
finding the draft shows; one that drops one is not posted, and the
draft is. An editor that finds
nothing in the draft the author needs to read says so in the words
``NOTHING_TO_RAISE`` holds, and no comment is posted. If the draft
has a failure, or reports something the author fixed, the draft is
posted instead.
"""

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import asdict

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.errors import (
    EditorUnavailableError,
    PublicationRejectedError,
    SubmissionNotFoundError,
)
from bugflow.review.domain.facts import (
    ACTION_TAKEN,
    COMMENT_EDITED,
    FINDING_RAISED,
    FINDING_REWRITTEN,
    LLM_CALLED,
)
from bugflow.review.domain.models.comment_edit import (
    CommentDraft,
    says_nothing_to_raise,
)
from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.enforcement import Enforcement, fails
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.journal_facts import (
    CommentEdit,
    ReviewAction,
    RewrittenFinding,
)
from bugflow.review.domain.models.recorder import Recorder
from bugflow.review.domain.models.review import (
    ReviewNote,
    ReviewStatus,
    ReviewVerdict,
    project,
)
from bugflow.review.domain.models.submission import Submission, SubmissionRef
from bugflow.review.domain.repositories.submission_source import (
    SubmissionSourceRepository,
)
from bugflow.review.domain.services.comment_editor import (
    CommentEditorService,
)
from bugflow.review.domain.services.enforcement import EnforcementService
from bugflow.review.domain.services.journal import JournalService
from bugflow.review.domain.services.publication import (
    CommitState,
    PublicationService,
)
from bugflow.review.domain.services.scoped_journal import for_run
from bugflow.review.domain.values.commentary import Seen, worth_saying
from bugflow.review.domain.values.passage import (
    passages,
    quoted,
    same_passage,
    stands,
)
from bugflow.review.domain.values.review_comments import (
    agent_comment,
    clause_page,
    findings_comment,
)
from bugflow.review.domain.values.withholding import drawn
from bugflow.review.dtos.publish_findings import (
    PublishFindingsRequest,
    PublishFindingsResponse,
)
from bugflow.review.usecases.model_calls import CALL_PAYLOAD, call_key
from bugflow.shared.domain.models.call_record import CallRecord
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.values.correlation import Correlation
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


#: A link in a comment, as a forge renders one: the address up to the
#: character that ends it in Markdown or HTML.
_LINK = re.compile(r"""https?://[^\s<>"')\]]+""")


def links_in(text: str) -> frozenset[str]:
    """The links a text holds, each once, without the punctuation a
    sentence ends one with."""
    return frozenset(found.rstrip(".,;:") for found in _LINK.findall(text))


def unmarked_draft(draft: str) -> str:
    """The draft without the markers the server reads, which the editor
    is given: each part's marker line is dropped, and the blank lines
    that follow it."""
    kept: list[str] = []
    for line in draft.splitlines():
        if line.startswith(MARKER_PREFIX):
            continue
        if not line.strip() and (not kept or not kept[-1].strip()):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


#: The three labels this use case sets and removes. It leaves every
#: other label alone.
MANAGED_LABELS = frozenset(("review:wip", "review:pass", "review:escalate"))
#: Statuses for an evaluation that wrote nothing: publishing is off for
#: the repository, the request asked for no publishing, or there was
#: nothing new to say.
DISABLED = "skipped: publishing disabled"
NOT_REQUESTED = "skipped: not published for this evaluation"
NOTHING_NEW = "skipped: nothing the last evaluation did not say"
#: The status of a comment the editor found nothing in to raise.
NOTHING_RAISED = "skipped: the editor found nothing to raise"


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


# A checkout agent's commit status and its text, for each verdict.
_AGENT_STATUS: dict[ReviewStatus, tuple[CommitState, str]] = {
    "pass": ("success", "nothing to raise"),
    "warn": ("success", "something to consider; advisory"),
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
    #: The clause page of each failing finding the body shows. The
    #: editor's comment must keep each one the draft links to.
    failing_links: tuple[str, ...] = ()


def _enforced(
    state: CommitState,
    description: str,
    verdict: str | None,
    agent_id: str,
    enforcement: Enforcement,
) -> tuple[CommitState, str]:
    """Apply the repository's enforcement to a commit status.

    A status fails only for a reviewer at ``gate`` on the repository,
    and only on a ``fail`` verdict. Otherwise a status that would have
    failed is set to success and marked "advisory". A warning's text
    says "advisory" already, because no behaviour fails a status on a
    warning.
    """
    if fails(enforcement, agent_id, verdict):
        return "failure", description
    if state == "failure":
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
        summaries: Mapping[str, str] | None = None,
        submissions: SubmissionSourceRepository | None = None,
        sites: Mapping[str, str] | None = None,
        editor: CommentEditorService | None = None,
    ) -> None:
        """``forge`` writes to the pull request. ``enforcement`` says which
        reviewers publish on a repository, and which of them gate and so
        decide its label. ``agents`` gives the policies of each installed
        reviewer, by agent id. ``summaries`` gives each policy's one-sentence
        summary, which a comment uses to name a rule. ``submissions``
        reads back the text of the pull request, so that a finding raised
        earlier can be checked against it; with none, no finding is
        carried and none is recorded as rewritten. ``sites`` gives the
        address each reviewer's gnome publishes its pages at, by agent
        id, which a comment links each clause it cites to. ``editor``
        writes the comment from the draft of the reviewers' parts;
        with none, the draft is the comment.
        """
        self._editor = editor
        self._forge = forge
        self._journal = journal
        self._clock = clock
        self._submissions = submissions
        self._enforcement = enforcement
        self._agents = dict(agents or {})
        self._summaries = dict(summaries or {})
        self._sites = dict(sites or {})

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

    def _submission(
        self, request: PublishFindingsRequest
    ) -> Submission | None:
        """The pull request as this evaluation read it, or None if it
        cannot be read back."""
        if self._submissions is None or request.snapshot_id is None:
            return None
        try:
            return self._submissions.get(
                SubmissionRef(snapshot_id=request.snapshot_id, ref=request.ref)
            )
        except SubmissionNotFoundError:
            return None

    def _text(self, request: PublishFindingsRequest) -> str | None:
        """Everything the pull request says that a policy may quote, as
        this evaluation read it. None if it cannot be read back.
        """
        submission = self._submission(request)
        return None if submission is None else passages(submission)

    def _edited(
        self,
        request: PublishFindingsRequest,
        parts: Sequence[_Said],
    ) -> tuple[str, CommentEdit | None, tuple[CallRecord, ...]]:
        """The comment to post for these parts, as the editor wrote it
        or as the draft is, with the fact that records the editing and
        the calls it made. Without an editor the draft is the comment
        and nothing is recorded."""
        draft = "\n\n".join(one.body for one in parts)
        if self._editor is None or not parts:
            return draft, None, ()
        reviewers = tuple(one.agent_id for one in parts)
        shown = unmarked_draft(draft)
        submission = self._submission(request)
        try:
            edited = self._editor.edit(
                CommentDraft(
                    text=shown,
                    reviewers=reviewers,
                    title=submission.title if submission else "",
                    description=submission.body if submission else "",
                )
            )
        except EditorUnavailableError as exc:
            return (
                draft,
                CommentEdit(
                    status=f"unavailable: {exc}",
                    draft=shown,
                    posted=shown,
                    reviewers=reviewers,
                ),
                tuple(exc.calls),
            )
        text = edited.text.strip()
        held = links_in(shown)
        if not text:
            return (
                draft,
                CommentEdit(
                    status="unavailable: the editor answered nothing",
                    draft=shown,
                    posted=shown,
                    model=edited.model,
                    reviewers=reviewers,
                    links_in_draft=len(held),
                    links_kept=len(held),
                ),
                tuple(edited.calls),
            )
        if says_nothing_to_raise(text):
            # The label and the commit status count a failing finding,
            # so the comment must show it. The author must also hear
            # that their fixes landed. Either way, the draft is posted.
            refused = (
                "a failure"
                if any(one.verdict == "fail" for one in parts)
                else "fixes"
                if any(one.fixed for one in parts)
                else None
            )
            return (
                draft if refused else "",
                CommentEdit(
                    status=(
                        "refused: the editor found nothing to raise in a "
                        f"draft that reports {refused}"
                        if refused
                        else "nothing to raise"
                    ),
                    draft=shown,
                    posted=shown if refused else "",
                    model=edited.model,
                    reviewers=reviewers,
                    links_in_draft=len(held),
                    links_kept=len(held) if refused else 0,
                ),
                tuple(edited.calls),
            )
        found = links_in(text)
        invented = sorted(found - held)
        if invented:
            # A link the draft did not hold leads the author somewhere
            # nothing vouches for. The draft is posted instead.
            return (
                draft,
                CommentEdit(
                    status=(
                        "refused: the editor added a link the draft does "
                        f"not hold: {invented[0]}"
                    ),
                    draft=shown,
                    posted=shown,
                    model=edited.model,
                    reviewers=reviewers,
                    links_in_draft=len(held),
                    links_kept=len(held),
                ),
                tuple(edited.calls),
            )
        required = {link for one in parts for link in one.failing_links}
        dropped = sorted((required & held) - found)
        if dropped:
            # The label and the commit status count each failing finding,
            # so the comment must show it. The draft is posted instead.
            return (
                draft,
                CommentEdit(
                    status=(
                        "refused: the editor dropped a failing finding: "
                        f"{dropped[0]}"
                    ),
                    draft=shown,
                    posted=shown,
                    model=edited.model,
                    reviewers=reviewers,
                    links_in_draft=len(held),
                    links_kept=len(held),
                ),
                tuple(edited.calls),
            )
        return (
            text,
            CommentEdit(
                status="edited",
                draft=shown,
                posted=text,
                model=edited.model,
                reviewers=reviewers,
                links_in_draft=len(held),
                links_kept=len(held & found),
            ),
            tuple(edited.calls),
        )

    def _carried(
        self,
        journal: JournalService,
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
            o.correlation.run_id: o.corpus_version
            for o in journal.observations_for_pull_request(request.ref)
        }
        latest: dict[tuple[str, str, str], tuple[str | None, Finding]] = {}
        for e in journal.events_for_pull_request(request.ref, FINDING_RAISED):
            if isinstance(e.fact, Finding):
                latest[_identity(e.fact)] = (
                    corpus_of_run.get(e.run_id),
                    e.fact,
                )
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
        journal: JournalService,
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
            _identity(e.fact.finding)
            for e in journal.events_for_pull_request(
                request.ref, FINDING_REWRITTEN
            )
            if isinstance(e.fact, RewrittenFinding)
        }
        gone: dict[tuple[str, str, str], Finding] = {}
        for f in previous:
            if _identity(f) in already or _identity(f) in gone:
                continue
            if stands(f, text) is False:
                gone[_identity(f)] = f
        return list(gone.values())

    def _previous_findings(
        self, journal: JournalService, request: PublishFindingsRequest
    ) -> tuple[Correlation | None, list[Finding]]:
        """The last evaluation before this one that decided what to
        publish, and the findings it raised, whether or not anything was
        published. A reviewer's first published comment shows all its
        findings whatever that evaluation raised.
        """
        previous = journal.latest_acted_run(
            request.ref, excluding=request.correlation
        )
        if previous is None:
            return None, []
        return previous, [
            e.fact
            for e in journal.entries_for_run(previous)
            if e.event_type == FINDING_RAISED and isinstance(e.fact, Finding)
        ]

    def _standing(
        self, journal: JournalService, request: PublishFindingsRequest
    ) -> set[tuple[str, str, str]]:
        """The findings that every evaluation of the present text raised,
        by identity.

        The entry for a finding does not say what text its evaluation
        read. The evaluation recorded that once, when it observed the
        pull request: the id of the stored submission. If no evaluation
        of this text has recorded a finding, or there is no last commit,
        this evaluation's own findings are returned.
        """
        if request.head_sha is None:
            return {_identity(f) for f in request.findings}
        read_by = {
            observed.correlation.run_id: observed.snapshot_id
            for observed in journal.observations_for_pull_request(request.ref)
        }
        here = read_by.setdefault(
            request.correlation.run_id,
            request.snapshot_id or request.head_sha,
        )
        history = [
            Seen(
                run_id=entry.run_id,
                read=read_by.get(entry.run_id) or "",
                finding=entry.fact,
            )
            for entry in journal.events_for_pull_request(
                request.ref, FINDING_RAISED
            )
            if isinstance(entry.fact, Finding)
        ]
        if not any(seen.read == here for seen in history):
            return {_identity(f) for f in request.findings}
        return {_identity(f) for f in worth_saying(history, read=here)}

    def _observed(
        self,
        journal: JournalService,
        ref: PullRequestRef,
        run: Correlation | None,
    ) -> tuple[str | None, str | None]:
        """The submission an earlier evaluation read and the corpus version
        it ran under.
        """
        if run is None:
            return None, None
        for observed in journal.observations_for_pull_request(ref):
            if observed.correlation == run:
                return observed.snapshot_id, observed.corpus_version
        return None, None

    def _spoken(
        self, journal: JournalService, ref: PullRequestRef, agent_id: str
    ) -> list[ReviewAction]:
        """The comments this reviewer has had posted on the pull request,
        oldest first. A comment that was worked out and not posted does
        not count.
        """
        return [
            e.fact
            for e in journal.events_for_pull_request(ref, ACTION_TAKEN)
            if isinstance(e.fact, ReviewAction)
            and e.fact.action == "review_comment"
            and e.fact.agent_id == agent_id
            and e.fact.performed
        ]

    def execute(
        self, request: PublishFindingsRequest
    ) -> PublishFindingsResponse:
        """Work out what to say, write it if publishing is on, and record
        what was done.
        """
        journal = for_run(self._journal, request.ref, request.correlation)
        previous, previous_findings = self._previous_findings(journal, request)
        resolved = resolved_since(
            previous_findings, request.findings, request.answered
        )
        dismissed_policies = {
            d.policy_id
            for d in journal.dismissals_for_pull_request(request.ref)
        }
        dismissed = tuple(
            f for f in request.findings if f.policy_id in dismissed_policies
        )
        enforcement = self._enforcement.enforcement_for(
            request.ref.forge, f"{request.ref.owner}/{request.ref.repo}"
        )
        governing = enforcement.deciding
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
            journal, request, current, text, dismissed_policies, kept_back
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
        stands = self._standing(journal, request)
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
        snapshot, corpus = self._observed(journal, request.ref, previous)
        rejudged = (
            request.snapshot_id is not None
            and snapshot == request.snapshot_id
            and corpus != request.corpus_version
        )
        said = [
            *self._findings_reviewers(
                journal,
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
            *self._checkout_reviewers(
                journal, request, governing, enforcement
            ),
        ]

        enabled = enforcement.publishes and request.publish
        if enabled:
            status = "published"
        else:
            status = DISABLED if not enforcement.publishes else NOT_REQUESTED

        def publishes(agent_id: str) -> bool:
            return request.publish and agent_id in enforcement.publishing

        def status_of(agent_id: str) -> str:
            if publishes(agent_id):
                return "published"
            if agent_id not in enforcement.publishing:
                return DISABLED
            return NOT_REQUESTED

        speaking = [
            one for one in said if one.body and publishes(one.agent_id)
        ]
        # What the editor is given: the parts that are posted, or, where
        # no reviewer publishes, every part that would have been.
        drafted = speaking or (
            [one for one in said if one.body]
            if not enforcement.publishing
            else []
        )
        comment, edit, edit_calls = self._edited(request, drafted)
        comment_ids: dict[str, int] = {}
        # An editor that found nothing to raise leaves no comment.
        quiet = bool(drafted) and not comment
        if speaking and not quiet:
            # The comment starts with the marker the forge matches on.
            # Without an editor, each reviewer's part keeps its own
            # marker inside it.
            marker = marker_for(request.correlation, "review")
            comment_id = self._forge.add_comment(
                request.ref, marker, "\n\n".join([marker, comment])
            )
            comment_ids = {one.agent_id: comment_id for one in speaking}
        if enabled:
            self._forge.set_labels(
                request.ref, add=frozenset({label}), remove=removed
            )
        statuses = {
            one.agent_id: self._set_status(
                request,
                one,
                publishes(one.agent_id),
                status_of(one.agent_id),
            )
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
                        "performed": publishes(one.agent_id)
                        and bool(one.body)
                        and not quiet,
                        "status": (
                            NOTHING_NEW
                            if not one.body
                            else NOTHING_RAISED
                            if quiet
                            else status_of(one.agent_id)
                        ),
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
        if edit is not None:
            entries += [
                recorder.entry(
                    LLM_CALLED,
                    call_key(call),
                    CALL_PAYLOAD.dump_python(call, mode="json"),
                )
                for call in edit_calls
            ]
            entries.append(
                recorder.entry(COMMENT_EDITED, "review_comment", asdict(edit))
            )
        if previous is not None:
            entries += recorder.resolutions(previous, resolved)
            entries += recorder.rewritten(
                previous,
                self._rewritten(
                    journal, request, [*previous_findings, *carried], text
                ),
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
        journal.append(entries)

        bodies = [one.body for one in said if one.body]
        return PublishFindingsResponse(
            status=(
                NOTHING_NEW
                if not bodies
                else NOTHING_RAISED
                if quiet and enabled
                else status
            ),
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
        journal: JournalService,
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
            spoken = self._spoken(journal, request.ref, agent_id)
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
                moved = now != spoken[-1].verdict
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
                        site=self._sites.get(agent_id, ""),
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
                    site=self._sites.get(agent_id, ""),
                )
            else:
                body = ""
            site = self._sites.get(agent_id, "")
            failing_links = (
                tuple(
                    dict.fromkeys(
                        clause_page(site, f.clause)
                        for f in new
                        if f.severity == "fail"
                    )
                )
                if body and site
                else ()
            )
            state, description = commit_status_for(mine, unanswered)
            state, description = _enforced(
                state,
                description,
                verdict.status if verdict else None,
                agent_id,
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
                    failing_links=failing_links,
                    dismissed=sum(
                        self._owner(f) == agent_id for f in dismissed
                    ),
                )
            )
        return said

    def _checkout_reviewers(
        self,
        journal: JournalService,
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
            spoken = self._spoken(journal, request.ref, agent_id)
            last = spoken[-1] if spoken else None
            speaks = (
                last is None
                or last.verdict != verdict.status
                or (
                    verdict.status != "pass"
                    and last.head_sha != verdict.head_sha
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
                agent_id,
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
