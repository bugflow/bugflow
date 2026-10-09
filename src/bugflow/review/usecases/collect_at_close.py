"""Record what a pull request's conversation says, once it has closed.

It runs once, when the pull request closes. By then the conversation is
over. It records three things:

- each reaction to a comment this server posted, as a "reaction
  recorded" fact;
- whether the pull request merged;
- which findings the last evaluation left standing.

The last two are in one "pull request closed" fact. What a reaction
means is left to whoever reads the journal.
"""

from bugflow.review.domain.facts import (
    ACTION_TAKEN,
    FINDING_RAISED,
    PR_CLOSED,
    REACTION_RECORDED,
)
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.recorder import Recorder
from bugflow.review.domain.services.conversation import ConversationService
from bugflow.review.domain.services.journal import JournalService
from bugflow.review.dtos.collect_at_close import (
    CollectAtCloseRequest,
    CollectAtCloseResponse,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.services.clock import ClockService


class CollectAtCloseUseCase:
    def __init__(
        self,
        journal: JournalService,
        conversation: ConversationService,
        clock: ClockService,
    ) -> None:
        self._journal = journal
        self._conversation = conversation
        self._clock = clock

    def execute(
        self, request: CollectAtCloseRequest
    ) -> CollectAtCloseResponse:
        """Record the reactions and the closing, and return counts of
        what was recorded.
        """
        ref = request.ref
        recorder = Recorder(ref, request.correlation, None, self._clock.now())
        entries: list[JournalEntry] = []
        drew_on = self._reviewers_by_comment(request)
        for comment_id, posted in self._posted(request).items():
            for reaction in self._conversation.reactions(ref, comment_id):
                entries.append(
                    recorder.entry(
                        REACTION_RECORDED,
                        f"{comment_id}/{reaction.login}/{reaction.content}",
                        {
                            "comment_id": comment_id,
                            # Every reviewer that had a part in the
                            # comment. A reaction is to the whole
                            # comment, so with several reviewers it is
                            # not known which part earned it, and
                            # "agent_id" is then None.
                            "agents": drew_on.get(comment_id, []),
                            "agent_id": posted.payload.get("agent_id")
                            if len(drew_on.get(comment_id, [])) == 1
                            else None,
                            "evaluated_in": posted.run_id,
                            "content": reaction.content,
                            "login": reaction.login,
                            "reacted_at": reaction.reacted_at.isoformat()
                            if reaction.reacted_at
                            else None,
                        },
                    )
                )
        closing = self._conversation.state(ref)
        outstanding = self._outstanding(request)
        entries.append(
            recorder.entry(
                PR_CLOSED,
                "closed",
                {
                    "merged": closing.merged,
                    "outstanding": [
                        {
                            "policy_id": f.policy_id,
                            "clause": f.clause,
                            "subject": f.subject,
                        }
                        for f in outstanding
                    ],
                    "reactions": len(entries),
                },
                commit_sha=closing.head_sha,
            )
        )
        self._journal.append(entries)
        return CollectAtCloseResponse(
            reactions=len(entries) - 1,
            merged=closing.merged,
            outstanding=len(outstanding),
        )

    def _posted(
        self, request: CollectAtCloseRequest
    ) -> dict[int, JournalEntry]:
        """Each comment that was posted, by its id, with the journal entry
        that recorded posting it.
        """
        posted: dict[int, JournalEntry] = {}
        for e in self._journal.events_for_pull_request(
            request.ref, ACTION_TAKEN
        ):
            comment_id = e.payload.get("comment_id")
            if (
                e.payload.get("action") == "review_comment"
                and e.payload.get("performed") is True
                and isinstance(comment_id, int)
            ):
                posted.setdefault(comment_id, e)
        return posted

    def _reviewers_by_comment(
        self, request: CollectAtCloseRequest
    ) -> dict[int, list[str]]:
        """The reviewers that had a part in each posted comment, sorted."""
        drew_on: dict[int, set[str]] = {}
        for e in self._journal.events_for_pull_request(
            request.ref, ACTION_TAKEN
        ):
            comment_id = e.payload.get("comment_id")
            agent_id = e.payload.get("agent_id")
            if (
                e.payload.get("action") == "review_comment"
                and e.payload.get("performed") is True
                and isinstance(comment_id, int)
                and isinstance(agent_id, str)
            ):
                drew_on.setdefault(comment_id, set()).add(agent_id)
        return {
            comment_id: sorted(agents)
            for comment_id, agents in drew_on.items()
        }

    def _outstanding(self, request: CollectAtCloseRequest) -> list[Finding]:
        """The findings the last evaluation that published raised. Each
        evaluation records every finding it holds, so these are what was
        still standing.
        """
        last = self._journal.latest_acted_run(
            request.ref, excluding=request.correlation
        )
        if last is None:
            return []
        return [
            Finding.from_payload(e.payload)
            for e in self._journal.entries_for_run(last)
            if e.event_type == FINDING_RAISED
        ]
