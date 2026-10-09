"""Read the whole record of one evaluation.

It reads the journal entries of the evaluation's workflow run, and the
stored judge exchanges that those entries name. It writes nothing and
calls no model.

Who may read a record is not decided here. The program that offers the
record checks that first.
"""

from collections.abc import Sequence

from bugflow.review.domain.errors import ExchangeNotFoundError
from bugflow.review.domain.facts import JUDGE_INVOKED
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.review.domain.models.record import review_record
from bugflow.review.domain.repositories.judge_archive import (
    JudgeArchiveRepository,
)
from bugflow.review.domain.services.journal import JournalService
from bugflow.review.dtos.read_review_record import (
    ReadReviewRecordRequest,
    ReadReviewRecordResponse,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry


class ReadReviewRecordUseCase:
    def __init__(
        self, journal: JournalService, archive: JudgeArchiveRepository
    ) -> None:
        self._journal = journal
        self._archive = archive

    def execute(
        self, request: ReadReviewRecordRequest
    ) -> ReadReviewRecordResponse:
        entries = self._journal.entries_for_run(request.correlation)
        exchanges: dict[str, JudgeExchange] = {}
        missing: list[str] = []
        for exchange_id in _exchange_ids(entries):
            try:
                exchanges[exchange_id] = self._archive.get(exchange_id)
            except ExchangeNotFoundError:
                # A stored exchange can be deleted. The journal entry
                # that names it cannot.
                missing.append(exchange_id)
        return ReadReviewRecordResponse(
            record=review_record(request.correlation, entries, exchanges),
            missing_exchanges=tuple(missing),
        )


def _exchange_ids(entries: Sequence[JournalEntry]) -> list[str]:
    """The id of every exchange the judgements name, each once, in the
    order they appear."""
    named = []
    for entry in entries:
        if entry.event_type != JUDGE_INVOKED:
            continue
        identity = entry.payload.get("identity") or {}
        exchange_id = identity.get("exchange_id")
        if exchange_id:
            named.append(str(exchange_id))
    return list(dict.fromkeys(named))
