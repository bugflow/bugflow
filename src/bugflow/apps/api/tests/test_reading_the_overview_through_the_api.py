"""Tests of the overview route and page of the operations views, over
in-memory stores."""

from datetime import timedelta

from bugflow.apps.api.tests.doubles import (
    ADMINISTRATOR,
    NOW,
    READER,
    Server,
    bearer,
)
from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.infrastructure.in_memory_spend_record import (
    RecordedCost,
)
from bugflow.shared.domain.values.budget import Budget

ROUTE = "/api/operations/overview"


def spent(server: Server) -> None:
    for run, repo, hours, usd in (
        ("run-1", "example-org/widgets", 1, 0.75),
        ("run-2", "example-org/gadgets", 2, 0.5),
        ("run-3", "example-org/widgets", 3, 0.25),
    ):
        server.spend.recorded.append(
            RecordedCost(
                workflow_id=f"review/{repo}/7",
                run_id=run,
                forge="github",
                repo=repo,
                agent_id="safety",
                kind="agent_dispatch",
                at=NOW - timedelta(hours=hours),
                usd=usd,
            )
        )


def test_the_overview_needs_the_settings_role() -> None:
    server = Server()
    assert server.client.get(ROUTE).status_code == 401
    assert server.client.get(ROUTE, headers=bearer(READER)).status_code == 403


def test_the_overview_reads_spend_allowances_and_the_latest_runs() -> None:
    server = Server()
    spent(server)
    server.ceilings.declare(
        SpendBinding(scope=SpendScope(agent_id="safety"), budget=Budget())
    )
    held = server.client.get(
        ROUTE, params={"recent": 2}, headers=bearer(ADMINISTRATOR)
    ).json()
    assert (held["spent_usd"], held["runs"]) == (1.5, 3)
    assert [(one["repo"], one["usd"]) for one in held["repositories"]] == [
        ("example-org/widgets", 1.0),
        ("example-org/gadgets", 0.5),
    ]
    assert [one["run_id"] for one in held["recent"]] == ["run-1", "run-2"]
    (allowance,) = held["allowances"]
    assert allowance["scope"]["agent_id"] == "safety"


def test_a_count_of_runs_out_of_bounds_is_refused() -> None:
    answered = Server().client.get(
        ROUTE, params={"recent": 0}, headers=bearer(ADMINISTRATOR)
    )
    assert answered.status_code == 422


def test_the_overview_page_is_served_where_the_pages_name_it() -> None:
    server = Server()
    moved = server.client.get("/operations", follow_redirects=False)
    assert moved.status_code in (307, 308)
    assert moved.headers["location"] == "/operations/"
    page = server.client.get("/operations/")
    assert "<title>Operations</title>" in page.text
    assert '<script src="../sign-in.js"></script>' in page.text
    for every in (
        "/operations/run",
        "/operations/repository",
        "/operations/layers",
        "/operations/agent",
        "/operations/allowances",
    ):
        assert '<a href="./">Overview</a>' in server.client.get(every).text
