"""Build the journal entries for calls to a model.

Every call to a model is recorded as an "LLM called" fact, whichever
step made it. What a repository has spent is added up from these facts,
so a step that calls a model must record each call.
"""

from collections.abc import Sequence
from datetime import datetime

from pydantic import TypeAdapter

from bugflow.review.domain.facts import LLM_CALLED
from bugflow.shared.domain.models.call_record import CallRecord
from bugflow.shared.domain.models.journal_entry import JournalEntry, event_id
from bugflow.shared.domain.values.correlation import Correlation

#: Turns a ``CallRecord`` into a payload. A call record has dates, and a
#: payload is stored as JSON, so the dates are written as text.
CALL_PAYLOAD: TypeAdapter[CallRecord] = TypeAdapter(CallRecord)


def call_key(call: CallRecord) -> str:
    """The key that tells one call's entry from another's in the same
    workflow run."""
    return f"llm/{call.call_id}"


def called(
    calls: Sequence[CallRecord],
    correlation: Correlation,
    occurred_at: datetime,
    *,
    forge: str,
    repo: str,
    pr_number: int | None,
    commit_sha: str | None,
    corpus_version: str | None,
    agent_id: str | None,
) -> list[JournalEntry]:
    """One "LLM called" entry for each call."""
    return [
        JournalEntry(
            event_id=event_id(correlation, LLM_CALLED, call_key(call)),
            occurred_at=occurred_at,
            event_type=LLM_CALLED,
            forge=forge,
            repo=repo,
            pr_number=pr_number,
            commit_sha=commit_sha,
            corpus_version=corpus_version,
            workflow_id=correlation.workflow_id,
            run_id=correlation.run_id,
            agent_id=agent_id,
            payload=CALL_PAYLOAD.dump_python(call, mode="json"),
        )
        for call in calls
    ]
