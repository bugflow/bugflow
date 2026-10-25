"""The review's test journal with the observation's question, as the
worker's activities take one journal for both."""

from bugflow.forge.domain.models.judgement import RecordedJudgement
from bugflow.review.domain.facts import JUDGE_INVOKED
from bugflow.review.domain.models.journal_facts import JudgeInvocation
from bugflow.review.tests.journal import QueryableJournal
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class ActivityJournal(QueryableJournal):
    """The in-memory journal with every question the activities ask."""

    def judgements_for_pull_request(
        self, ref: PullRequestRef
    ) -> list[RecordedJudgement]:
        return [
            RecordedJudgement(
                policy_id=e.fact.policy_id,
                input_hash=e.fact.identity.input_hash
                if e.fact.identity
                else None,
                status=e.fact.status,
                corpus_version=e.corpus_version,
            )
            for e in self.events_for_pull_request(ref, JUDGE_INVOKED)
            if isinstance(e.fact, JudgeInvocation)
        ]
