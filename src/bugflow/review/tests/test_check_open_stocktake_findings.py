"""Tests of ``CheckOpenStocktakeFindingsUseCase``: a stocktake's finding
is open until its latest disposition closes it."""

from collections.abc import Sequence
from datetime import UTC, datetime

from bugflow.review.domain.models.stocktake_finding import (
    FindingDisposition,
    StocktakeFinding,
)
from bugflow.review.dtos.check_open_stocktake_findings import (
    CheckOpenStocktakeFindingsRequest,
)
from bugflow.review.dtos.declared_checks import DECLARED_CHECKS
from bugflow.review.usecases.check_open_stocktake_findings import (
    CheckOpenStocktakeFindingsUseCase,
)
from bugflow.shared.domain.values.disposition import Disposition


def found(event_id: str, day: int) -> StocktakeFinding:
    return StocktakeFinding(
        event_id=event_id,
        forge="github",
        repo="orchard/pear-tree",
        layer="week",
        agent_id="safety",
        head_sha="a" * 40,
        workflow_id="stocktake/week",
        run_id="run-1",
        found_at=datetime(2030, 3, day, tzinfo=UTC),
        index=0,
        where="src/poller.py",
        quote="while True:",
        claim="The loop never sleeps.",
        kind="defect",
    )


def disposed(
    finding: str, disposition: Disposition, day: int, question_id: str = ""
) -> FindingDisposition:
    return FindingDisposition(
        finding=finding,
        disposition=disposition,
        question_id=question_id,
        disposed_at=datetime(2030, 4, day, tzinfo=UTC),
    )


class Findings:
    """A fixed set of findings and dispositions."""

    def __init__(
        self,
        findings: Sequence[StocktakeFinding],
        dispositions: Sequence[FindingDisposition] = (),
    ) -> None:
        self._findings = findings
        self._dispositions = dispositions

    def found(self) -> Sequence[StocktakeFinding]:
        return self._findings

    def dispositions(self) -> Sequence[FindingDisposition]:
        return self._dispositions


def open_ids(findings: Findings) -> list[str]:
    response = CheckOpenStocktakeFindingsUseCase(findings).execute(
        CheckOpenStocktakeFindingsRequest()
    )
    return [f.event_id for f in response.open_findings]


def test_a_finding_with_no_disposition_is_open() -> None:
    findings = Findings([found("f-1", 1), found("f-2", 2)])

    assert open_ids(findings) == ["f-1", "f-2"]


def test_done_and_rejected_close_a_finding() -> None:
    findings = Findings(
        [found("f-1", 1), found("f-2", 2), found("f-3", 3)],
        [disposed("f-1", "accepted_done", 1), disposed("f-2", "rejected", 2)],
    )

    assert open_ids(findings) == ["f-3"]


def test_deferred_and_pending_findings_stay_open() -> None:
    findings = Findings(
        [found("f-1", 1), found("f-2", 2)],
        [
            disposed("f-1", "deferred", 1),
            disposed("f-2", "accepted_follow_up_pending", 2),
        ],
    )

    assert open_ids(findings) == ["f-1", "f-2"]


def test_a_finding_routed_to_a_question_stays_open() -> None:
    findings = Findings(
        [found("f-1", 1)],
        [disposed("f-1", "routed_to_question", 1, question_id="q-1")],
    )

    assert open_ids(findings) == ["f-1"]


def test_the_latest_disposition_is_the_one_that_counts() -> None:
    findings = Findings(
        [found("f-1", 1), found("f-2", 2)],
        [
            disposed("f-1", "deferred", 1),
            disposed("f-1", "accepted_done", 2),
            disposed("f-2", "rejected", 1),
            disposed("f-2", "deferred", 2),
        ],
    )

    assert open_ids(findings) == ["f-2"]


def test_an_open_finding_carries_what_a_reader_needs() -> None:
    response = CheckOpenStocktakeFindingsUseCase(
        Findings([found("f-1", 1)])
    ).execute(CheckOpenStocktakeFindingsRequest())

    (one,) = response.open_findings
    assert (one.where, one.quote, one.claim, one.kind) == (
        "src/poller.py",
        "while True:",
        "The loop never sleeps.",
        "defect",
    )
    assert (one.layer, one.agent_id) == ("week", "safety")


def test_the_check_is_declared_with_the_field_that_holds_its_rows() -> None:
    (check,) = DECLARED_CHECKS
    assert check.id == "stocktake.open-findings"
    assert check.rows == ("open_findings",)
    assert set(check.rows) <= set(check.response_model.model_fields)
