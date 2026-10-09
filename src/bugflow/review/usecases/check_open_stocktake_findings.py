"""List the findings that stocktakes raised and nobody has closed.

A finding is closed by the latest disposition recorded for it, by the
rule in ``closes_finding``: "accepted_done" and "rejected" close it.

A finding routed to a question would close when the question is
answered. This context does not know which questions have been
answered, so here such a finding stays open.

It only reads.
"""

from bugflow.review.domain.services.stocktake_findings import (
    StocktakeFindingsService,
)
from bugflow.review.dtos.check_open_stocktake_findings import (
    CheckOpenStocktakeFindingsRequest,
    CheckOpenStocktakeFindingsResponse,
    OpenStocktakeFinding,
)
from bugflow.shared.domain.values.disposition import closes_finding


class CheckOpenStocktakeFindingsUseCase:
    def __init__(self, findings: StocktakeFindingsService) -> None:
        self._findings = findings

    def execute(
        self, request: CheckOpenStocktakeFindingsRequest
    ) -> CheckOpenStocktakeFindingsResponse:
        """Return every open finding, oldest first."""
        latest = {d.finding: d for d in self._findings.dispositions()}
        closed = {
            finding
            for finding, d in latest.items()
            if closes_finding(
                d.disposition, d.question_id or None, frozenset()
            )
        }
        return CheckOpenStocktakeFindingsResponse(
            open_findings=tuple(
                OpenStocktakeFinding(
                    event_id=f.event_id,
                    forge=f.forge,
                    repo=f.repo,
                    layer=f.layer,
                    agent_id=f.agent_id,
                    head_sha=f.head_sha,
                    found_at=f.found_at,
                    where=f.where,
                    quote=f.quote,
                    claim=f.claim,
                    kind=f.kind,
                )
                for f in self._findings.found()
                if f.event_id not in closed
            )
        )
