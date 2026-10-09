"""Work out the range one stocktake covers, and leave the layer's mark.

A stocktake covers what merged in a repository between the layer's last
mark and now. This use case works out that range and records a new
mark. It records the mark whether or not anything merged. Otherwise a
layer with a quiet period would cover the same period again next time.

It reviews nothing. What is done with the range is up to the caller.
"""

from bugflow.review.domain.facts import PR_MERGED, STOCKTAKE_TAKEN
from bugflow.review.domain.models.stocktake import (
    Mark,
    Merged,
    stocktake_range,
)
from bugflow.review.domain.services.journal import JournalService
from bugflow.review.dtos.take_stock import TakeStockRequest, TakeStockResponse
from bugflow.shared.domain.models.journal_entry import JournalEntry, event_id
from bugflow.shared.domain.services.clock import ClockService


class TakeStockUseCase:
    def __init__(self, journal: JournalService, clock: ClockService) -> None:
        self._journal = journal
        self._clock = clock

    def execute(self, request: TakeStockRequest) -> TakeStockResponse:
        now = self._clock.now()
        taken = stocktake_range(
            now=now,
            mark=self._mark(request),
            merged=[
                Merged(
                    pull_request=entry.pr_number or 0,
                    head_sha=entry.commit_sha or "",
                    merged_at=entry.occurred_at,
                )
                for entry in self._journal.events_for_repository(
                    request.forge, request.repo, PR_MERGED
                )
            ],
        )
        self._journal.append(
            [
                JournalEntry(
                    event_id=event_id(
                        request.correlation, STOCKTAKE_TAKEN, request.layer
                    ),
                    occurred_at=now,
                    event_type=STOCKTAKE_TAKEN,
                    forge=request.forge,
                    repo=request.repo,
                    pr_number=None,
                    commit_sha=None,
                    corpus_version=None,
                    workflow_id=request.correlation.workflow_id,
                    run_id=request.correlation.run_id,
                    payload={
                        "layer": request.layer,
                        "since": (
                            taken.since.isoformat() if taken.since else None
                        ),
                        "until": taken.until.isoformat(),
                        "merged": len(taken.merged),
                        "pull_requests": [
                            m.pull_request for m in taken.merged
                        ],
                        "base_sha": taken.base_sha,
                        "head_sha": taken.head_sha,
                    },
                )
            ]
        )
        return TakeStockResponse(
            since=taken.since,
            until=taken.until,
            merged=len(taken.merged),
            worth_taking=taken.worth_taking,
            base_sha=taken.base_sha,
            head_sha=taken.head_sha,
        )

    def _mark(self, request: TakeStockRequest) -> Mark | None:
        """The layer's latest mark on the repository, or None if it has
        left none.

        Journal entries are never changed, so there is a mark for every
        stocktake, and the last one is the mark.
        """
        marks = [
            entry
            for entry in self._journal.events_for_repository(
                request.forge, request.repo, STOCKTAKE_TAKEN
            )
            if entry.payload.get("layer") == request.layer
        ]
        if not marks:
            return None
        last = marks[-1]
        # The commit is taken from the latest mark that has one. A
        # stocktake of an empty range records the time and no commit,
        # so a quiet period does not change what the next review
        # compares against.
        stopped_at = next(
            (
                one.payload.get("head_sha")
                for one in reversed(marks)
                if one.payload.get("head_sha")
            ),
            None,
        )
        return Mark(taken_at=last.occurred_at, head_sha=stopped_at)
