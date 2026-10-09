"""A helper that builds the journal entries about findings.

It adds four kinds of entry to the shared ``Recorder``. Each entry about
a finding is recorded under the reviewer that raised the finding and
that reviewer's corpus version, which the finding carries.
"""

from collections.abc import Sequence
from dataclasses import asdict

from bugflow.review.domain.facts import (
    FINDING_RAISED,
    FINDING_RESOLVED,
    FINDING_REWRITTEN,
    FINDING_WITHHELD,
)
from bugflow.review.domain.models.finding import Finding
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.models.recorder import Recorder as _Recorder
from bugflow.shared.domain.values.correlation import Correlation


class Recorder(_Recorder):
    def findings(
        self, step: str, findings: Sequence[Finding]
    ) -> list[JournalEntry]:
        """One "finding raised" entry for each finding. ``step`` names
        the step that raised them, so that two steps raising the same
        finding record two entries."""
        return [
            self.entry(
                FINDING_RAISED,
                f"{step}/{n}/{f.policy_id}/{f.subject}",
                asdict(f),
                agent_id=f.agent_id,
                corpus_version=f.corpus_version,
            )
            for n, f in enumerate(findings)
        ]

    def resolutions(
        self, raised_in: Correlation, findings: Sequence[Finding]
    ) -> list[JournalEntry]:
        """One "finding resolved" entry for each finding. ``raised_in``
        is the workflow run that raised them."""
        return [
            self.entry(
                FINDING_RESOLVED,
                f"{f.policy_id}/{f.clause}/{f.subject}",
                {
                    **asdict(f),
                    "raised_in_workflow_id": raised_in.workflow_id,
                    "raised_in_run_id": raised_in.run_id,
                },
                agent_id=f.agent_id,
                corpus_version=f.corpus_version,
            )
            for f in findings
        ]

    def rewritten(
        self, raised_in: Correlation, findings: Sequence[Finding]
    ) -> list[JournalEntry]:
        """One "finding rewritten" entry for each finding whose quoted
        words are gone from the pull request. An evaluation records it
        once for a finding."""
        return [
            self.entry(
                FINDING_REWRITTEN,
                f"{f.policy_id}/{f.clause}/{f.subject}",
                {
                    **asdict(f),
                    "raised_in_workflow_id": raised_in.workflow_id,
                    "raised_in_run_id": raised_in.run_id,
                },
                agent_id=f.agent_id,
                corpus_version=f.corpus_version,
            )
            for f in findings
        ]

    def withheld(
        self, share: float, findings: Sequence[Finding]
    ) -> list[JournalEntry]:
        """One "finding withheld" entry for each warning kept out of the
        pull request, with the share that was being kept out."""
        return [
            self.entry(
                FINDING_WITHHELD,
                f"{f.policy_id}/{f.clause}/{f.subject}",
                {**asdict(f), "share": share},
                agent_id=f.agent_id,
                corpus_version=f.corpus_version,
            )
            for f in findings
        ]
