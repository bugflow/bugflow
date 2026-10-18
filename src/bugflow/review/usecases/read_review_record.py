"""Read the whole record of one evaluation.

It reads the journal entries of the evaluation's workflow run, and the
stored judge exchanges that those entries name. It writes nothing and
calls no model.

Who may read a record is not decided here. The program that offers the
record checks that first.
"""

from collections.abc import Sequence
from dataclasses import replace

from bugflow.review.domain.errors import (
    ExchangeNotFoundError,
    HistoryTooLargeError,
    ReviewRecordNotFoundError,
    SubmissionNotFoundError,
)
from bugflow.review.domain.facts import JUDGE_INVOKED
from bugflow.review.domain.models.history import (
    HistoryLimits,
    HistoryScope,
    StoredReviewEvent,
    observed_review_run,
)
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.review.domain.models.record import review_record
from bugflow.review.domain.models.submission import Submission, SubmissionRef
from bugflow.review.domain.repositories.judge_archive import (
    BoundedJudgeArchiveRepository,
)
from bugflow.review.domain.repositories.submission_source import (
    BoundedSubmissionSourceRepository,
)
from bugflow.review.domain.services.journal import HistoryService
from bugflow.review.dtos.read_review_record import (
    ReadReviewHistoryRequest,
    ReadReviewHistoryResponse,
    ReadReviewRecordRequest,
    ReadReviewRecordResponse,
)
from bugflow.shared.domain.errors import ContentTooLargeError
from bugflow.shared.domain.models.journal_entry import JournalEntry


class ReadReviewRecordUseCase:
    def __init__(
        self,
        journal: HistoryService,
        archive: BoundedJudgeArchiveRepository,
        submissions: BoundedSubmissionSourceRepository | None = None,
        limits: HistoryLimits | None = None,
    ) -> None:
        self._journal = journal
        self._archive = archive
        self._submissions = submissions
        self._limits = limits or HistoryLimits()

    def execute(
        self, request: ReadReviewRecordRequest
    ) -> ReadReviewRecordResponse:
        scope = HistoryScope(
            forge=request.ref.forge,
            repo=f"{request.ref.owner}/{request.ref.repo}",
            pr_numbers=(request.ref.number,),
            correlation=request.correlation,
            origin=request.origin,
        )
        events = self._journal.entries_for_history(scope, self._limits)
        if not events:
            raise ReviewRecordNotFoundError("no evaluation in this scope")
        entries = tuple(event.entry for event in events)
        references = observed_review_run(events, None).content_references
        remaining = self._limits.max_bytes
        exchanges: dict[str, JudgeExchange] = {}
        missing: list[str] = []
        for exchange_id in _exchange_ids(entries):
            try:
                exchange, size = self._archive.get_bounded(
                    exchange_id, remaining
                )
                exchanges[exchange_id] = exchange
                remaining -= size
            except ContentTooLargeError as exc:
                raise HistoryTooLargeError(
                    "evaluation content exceeds its byte limit"
                ) from exc
            except ExchangeNotFoundError:
                missing.append(exchange_id)
        submissions: dict[str, Submission] = {}
        missing_submissions: list[str] = []
        snapshot_ids = dict.fromkeys(
            reference.content_id
            for reference in references
            if reference.kind == "snapshot" and reference.content_id
        )
        if self._submissions is not None:
            for snapshot_id in snapshot_ids:
                try:
                    submission, size = self._submissions.get_bounded(
                        SubmissionRef(
                            snapshot_id=snapshot_id,
                            ref=request.ref,
                            origin=request.origin,
                        ),
                        remaining,
                    )
                    submissions[snapshot_id] = submission
                    remaining -= size
                except ContentTooLargeError as exc:
                    raise HistoryTooLargeError(
                        "evaluation content exceeds its byte limit"
                    ) from exc
                except SubmissionNotFoundError:
                    missing_submissions.append(snapshot_id)
        availability: dict[tuple[str, str | None], str] = {
            ("exchange", identity): "available" for identity in exchanges
        }
        availability.update(
            {("exchange", identity): "missing" for identity in missing}
        )
        availability.update(
            {("snapshot", identity): "available" for identity in submissions}
        )
        availability.update(
            {
                ("snapshot", identity): "missing"
                for identity in missing_submissions
            }
        )
        response = ReadReviewRecordResponse(
            record=review_record(request.correlation, entries, exchanges),
            events=events,
            missing_exchanges=tuple(missing),
            submissions=submissions,
            missing_submissions=tuple(missing_submissions),
            content_references=tuple(
                replace(
                    reference,
                    availability=availability.get(
                        (reference.kind, reference.content_id),
                        reference.availability,
                    ),
                )
                for reference in references
            ),
        )
        if (
            len(response.model_dump_json().encode("utf-8"))
            > self._limits.max_bytes
        ):
            raise HistoryTooLargeError(
                "evaluation detail exceeds its response byte limit"
            )
        return response


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


class ReadReviewHistoryUseCase:
    def __init__(
        self, history: HistoryService, limits: HistoryLimits | None = None
    ) -> None:
        self._history = history
        self._limits = limits or HistoryLimits()

    def execute(
        self, request: ReadReviewHistoryRequest
    ) -> ReadReviewHistoryResponse:
        events = self._history.entries_for_history(request.scope, self._limits)
        if len(events) > self._limits.max_events:
            raise HistoryTooLargeError("history exceeds its event limit")
        groups: dict[tuple[int, str, str], list[StoredReviewEvent]] = {}
        for event in events:
            entry = event.entry
            assert entry.pr_number is not None
            key = (entry.pr_number, entry.workflow_id, entry.run_id)
            groups.setdefault(key, []).append(event)
        observed = tuple(sorted({key[0] for key in groups}))
        response = ReadReviewHistoryResponse(
            scope=request.scope,
            policy_id=request.policy_id,
            runs=tuple(
                observed_review_run(tuple(groups[key]), request.policy_id)
                for key in sorted(groups)
            ),
            observed_pr_numbers=observed,
            unobserved_pr_numbers=tuple(
                number
                for number in request.scope.pr_numbers
                if number not in observed
            ),
            event_count=len(events),
        )
        if (
            len(response.model_dump_json().encode("utf-8"))
            > self._limits.max_bytes
        ):
            raise HistoryTooLargeError(
                "history exceeds its response byte limit"
            )
        return response
