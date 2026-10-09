"""Choose the findings that a comment about a pull request's last
commit should carry.

It reads what every evaluation of the pull request recorded, and
returns the findings worth putting in one comment. The rule for which
those are is ``worth_saying``. It writes nothing and calls no model.
"""

from bugflow.review.domain.facts import FINDING_RAISED, PR_OBSERVED
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.services.journal import JournalService
from bugflow.review.domain.values.commentary import Seen, worth_saying
from bugflow.review.dtos.choose_what_to_say import (
    ChooseWhatToSayRequest,
    ChooseWhatToSayResponse,
)


class ChooseWhatToSayUseCase:
    def __init__(self, journal: JournalService) -> None:
        self._journal = journal

    def execute(
        self, request: ChooseWhatToSayRequest
    ) -> ChooseWhatToSayResponse:
        # The entry for a finding does not give the commit. The
        # evaluation that raised it recorded the commit once, when it
        # read the pull request. So the commit of each workflow run is
        # taken from there.
        head_of = {
            entry.run_id: entry.commit_sha or ""
            for entry in self._journal.events_for_pull_request(
                request.ref, PR_OBSERVED
            )
        }
        history = [
            Seen(
                run_id=entry.run_id,
                read=head_of.get(entry.run_id, entry.commit_sha or ""),
                finding=Finding.from_payload(entry.payload),
            )
            for entry in self._journal.events_for_pull_request(
                request.ref, FINDING_RAISED
            )
        ]
        at_head = {
            (s.finding.policy_id, s.finding.clause, s.finding.subject)
            for s in history
            if s.read == request.head_sha
        }
        return ChooseWhatToSayResponse(
            findings=worth_saying(history, read=request.head_sha),
            considered=len(at_head),
        )
