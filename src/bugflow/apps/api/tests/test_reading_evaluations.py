"""Evaluation routes check access before reading scoped evidence."""

from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bugflow.apps.api.api import PolicyDeploying, create_api
from bugflow.apps.api.evaluations import EvaluationReading
from bugflow.apps.api.role_policy_deployment_access import (
    RolePolicyDeploymentAccess,
)
from bugflow.apps.api.tests.doubles import (
    DEPLOYER,
    NOW,
    Server,
    Tokens,
    bearer,
)
from bugflow.review.domain.models.history import (
    HistoryLimits,
    HistoryScope,
    StoredReviewEvent,
)
from bugflow.review.dtos.read_review_record import ReadReviewHistoryRequest
from bugflow.review.infrastructure.in_memory_history import InMemoryHistory
from bugflow.review.infrastructure.in_memory_judge_archive import (
    InMemoryJudgeArchive,
)
from bugflow.review.usecases.read_review_record import (
    ReadReviewHistoryUseCase,
    ReadReviewRecordUseCase,
)
from bugflow.shared.domain.models.recorder import Recorder
from bugflow.shared.domain.values.caller import Caller
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(
    forge="github", owner="orchard", repo="pear-tree", number=5
)
RUN = Correlation(workflow_id="review/pr/5", run_id="run/one")
PREFIX = "/api/repositories/github/orchard/pear-tree"
HISTORY = PREFIX + "/evaluations"
DETAIL = PREFIX + "/pull-requests/5/evaluation"
SELECTOR = {"workflow_id": RUN.workflow_id, "run_id": RUN.run_id}


def fact(
    kind: str = "pr.observed",
    *,
    payload: dict[str, Any] | None = None,
    ref: PullRequestRef = REF,
    run: Correlation = RUN,
) -> StoredReviewEvent:
    return StoredReviewEvent(
        entry=Recorder(ref, run, "build", NOW).entry(
            kind,
            f"{ref.forge}/{ref.owner}/{ref.repo}/{ref.number}/{kind}",
            payload or {},
        )
    )


class Access:
    def __init__(self, allowed: tuple[int, ...]) -> None:
        self.allowed = allowed
        self.checked: list[PullRequestRef] = []

    def may_read(
        self, caller: Caller, ref: PullRequestRef, *, origin: str | None = None
    ) -> bool:
        self.checked.append(ref)
        return ref.number in self.allowed


class CountedHistory(InMemoryHistory):
    reads = 0

    def entries_for_history(
        self, scope: HistoryScope, limits: HistoryLimits
    ) -> tuple[StoredReviewEvent, ...]:
        self.reads += 1
        return super().entries_for_history(scope, limits)


class ReadingServer:
    def __init__(
        self,
        events: tuple[StoredReviewEvent, ...] = (),
        *,
        allowed: tuple[int, ...] = (5, 6),
        limits: HistoryLimits | None = None,
    ) -> None:
        self.access = Access(allowed)
        self.history = CountedHistory(list(events))
        self.archive = InMemoryJudgeArchive()
        self.reader = ReadReviewHistoryUseCase(self.history, limits)
        deploying = Server().deploying
        self.client = TestClient(
            create_api(
                Tokens(),
                PolicyDeploying(
                    access=RolePolicyDeploymentAccess(DEPLOYER),
                    deploying=deploying,
                ),
                reading=EvaluationReading(
                    self.access,
                    self.reader,
                    ReadReviewRecordUseCase(
                        self.history, self.archive, limits=limits
                    ),
                ),
            )
        )


@pytest.mark.parametrize(
    "route,params", [(HISTORY, {"pr_number": 5}), (DETAIL, SELECTOR)]
)
@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Basic abc"}, bearer("refused")]
)
def test_authentication_precedes_access_and_evidence(
    route: str, params: dict[str, Any], headers: dict[str, str]
) -> None:
    server = ReadingServer((fact(),))
    response = server.client.get(route, params=params, headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert server.access.checked == []
    assert server.history.reads == 0


def test_one_denied_pr_refuses_the_whole_batch_before_any_evidence_read() -> (
    None
):
    server = ReadingServer((fact(),), allowed=(5,))
    response = server.client.get(
        HISTORY,
        params=[("pr_number", 5), ("pr_number", 6)],
        headers=bearer("nobody"),
    )
    assert response.status_code == 403
    assert [ref.number for ref in server.access.checked] == [5, 6]
    assert server.history.reads == 0
    assert "runs" not in response.json()


def test_history_preserves_the_response_with_policy_and_coverage() -> None:
    server = ReadingServer(
        (
            fact(),
            fact(
                "policy.checked",
                payload={"policy_id": "P-01", "finding_count": 0},
            ),
        )
    )
    expected = server.reader.execute(
        ReadReviewHistoryRequest(
            scope=HistoryScope(
                forge="github", repo="orchard/pear-tree", pr_numbers=(5, 6)
            ),
            policy_id="P-01",
        )
    )
    server.history.reads = 0
    response = server.client.get(
        HISTORY,
        params=[
            ("pr_number", "6"),
            ("pr_number", "5"),
            ("pr_number", "5"),
            ("policy_id", "P-01"),
        ],
        headers=bearer("nobody"),
    )
    assert response.status_code == 200
    assert response.json() == expected.model_dump(mode="json")
    assert response.json()["unobserved_pr_numbers"] == [6]
    assert server.access.checked == [REF, replace(REF, number=6)]
    assert server.history.reads == 1


def test_detail_preserves_missing_content_and_slashes_in_identifiers() -> None:
    server = ReadingServer(
        (
            fact(
                "judge.invoked",
                payload={
                    "policy_id": "P-01",
                    "status": "judged",
                    "identity": {"exchange_id": "gone"},
                },
            ),
        )
    )
    response = server.client.get(
        DETAIL, params=SELECTOR, headers=bearer("nobody")
    )
    assert response.status_code == 200
    assert response.json()["record"]["correlation"] == SELECTOR
    assert response.json()["missing_exchanges"] == ["gone"]
    assert any(
        ref["content_id"] == "gone" and ref["availability"] == "missing"
        for ref in response.json()["content_references"]
    )


@pytest.mark.parametrize(
    "foreign",
    [
        fact(ref=replace(REF, owner="other")),
        fact(ref=replace(REF, number=6)),
        fact(ref=replace(REF, forge="forgejo")),
        fact(run=replace(RUN, run_id="another")),
    ],
)
def test_detail_does_not_read_another_scope_or_run(
    foreign: StoredReviewEvent,
) -> None:
    server = ReadingServer((foreign,))
    response = server.client.get(
        DETAIL, params=SELECTOR, headers=bearer("nobody")
    )
    assert response.status_code == 404
    assert server.history.reads == 1


def test_denied_detail_is_refused_before_missing_record_is_disclosed() -> None:
    server = ReadingServer(allowed=())
    response = server.client.get(
        DETAIL, params=SELECTOR, headers=bearer("nobody")
    )
    assert response.status_code == 403
    assert server.history.reads == 0


@pytest.mark.parametrize(
    "route,params", [(HISTORY, {"pr_number": 5}), (DETAIL, SELECTOR)]
)
def test_oversized_evidence_is_rejected_without_a_partial_response(
    route: str, params: dict[str, Any]
) -> None:
    server = ReadingServer(
        (fact(), fact("policy.checked")), limits=HistoryLimits(max_events=1)
    )
    response = server.client.get(
        route, params=params, headers=bearer("nobody")
    )
    assert response.status_code == 413
    assert "runs" not in response.json()
    assert "events" not in response.json()


@pytest.mark.parametrize(
    "route,params",
    [
        (HISTORY, {}),
        (HISTORY, {"pr_number": 0}),
        (HISTORY, {"pr_number": -1}),
        (HISTORY, {"pr_number": "bad"}),
        (HISTORY, {"pr_number": [5] * 101}),
        (HISTORY, {"pr_number": 5, "policy_id": ""}),
        (DETAIL, {}),
        (DETAIL, SELECTOR | {"workflow_id": ""}),
        (DETAIL, SELECTOR | {"run_id": "   "}),
        (PREFIX + "/pull-requests/0/evaluation", SELECTOR),
        (HISTORY.replace("github", "unknown"), {"pr_number": 5}),
    ],
)
def test_invalid_selectors_do_not_reach_evidence(
    route: str, params: dict[str, Any]
) -> None:
    server = ReadingServer((fact(),))
    response = server.client.get(
        route, params=params, headers=bearer("nobody")
    )
    assert response.status_code == 422
    assert server.history.reads == 0
