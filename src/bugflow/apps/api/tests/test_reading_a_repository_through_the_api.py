"""Tests of the repository route and page of the operations views, over
in-memory stores."""

from datetime import timedelta

from bugflow.apps.api.tests.doubles import (
    ADMINISTRATOR,
    NOW,
    READER,
    Server,
    bearer,
)
from bugflow.review.domain.models.gnome_setting import GnomeSetting
from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.infrastructure.in_memory_spend_record import (
    RecordedCost,
)
from bugflow.shared.domain.values.budget import Budget

ROUTE = "/api/operations/repositories/github/example-org/widgets"


def spent(server: Server) -> None:
    """Two runs on the repository, one of them long ago."""
    for run, agent, ago, usd in (
        ("run-1", "safety", timedelta(hours=1), 0.75),
        ("run-1", "", timedelta(hours=1), 0.25),
        ("run-2", "safety", timedelta(days=40), 5.0),
    ):
        server.spend.recorded.append(
            RecordedCost(
                workflow_id="review/example-org/widgets/7",
                run_id=run,
                forge="github",
                repo="example-org/widgets",
                agent_id=agent,
                kind="agent_dispatch" if agent else "model_call",
                at=NOW - ago,
                usd=usd,
            )
        )


def test_a_repository_needs_the_settings_role() -> None:
    server = Server()
    assert server.client.get(ROUTE).status_code == 401
    assert server.client.get(ROUTE, headers=bearer(READER)).status_code == 403


def test_a_repository_is_read_over_the_thirty_days_to_now() -> None:
    server = Server()
    spent(server)
    server.settings.save(
        GnomeSetting(
            forge="github",
            repo="example-org/widgets",
            gnome="safety",
            behaviour="advise",
        )
    )
    server.ceilings.declare(
        SpendBinding(
            scope=SpendScope(forge="github", repo="example-org/widgets"),
            budget=Budget(usd=2.0),
        )
    )
    answered = server.client.get(ROUTE, headers=bearer(ADMINISTRATOR))
    assert answered.status_code == 200
    held = answered.json()
    assert (held["repo"], held["spent_usd"]) == ("example-org/widgets", 1.0)
    assert (held["since"], held["until"]) == (
        (NOW - timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        NOW.isoformat().replace("+00:00", "Z"),
    )
    assert [(one["gnome"], one["behaviour"]) for one in held["settings"]] == [
        ("safety", "advise")
    ]
    assert [(one["agent_id"], one["usd"]) for one in held["spend"]] == [
        ("safety", 0.75),
        ("", 0.25),
    ]
    (allowance,) = held["allowances"]
    assert (allowance["per"], allowance["spent_usd"]) == ("event", None)
    assert [one["run_id"] for one in held["runs"]] == ["run-1"]


def test_a_spend_row_lists_the_runs_it_is_made_of() -> None:
    server = Server()
    spent(server)
    answered = server.client.get(
        ROUTE,
        params={
            "since": (NOW - timedelta(days=60)).isoformat(),
            "layer": "",
            "agent_id": "safety",
        },
        headers=bearer(ADMINISTRATOR),
    )
    held = answered.json()
    assert (held["layer"], held["agent_id"]) == ("", "safety")
    assert [(one["run_id"], one["usd"]) for one in held["runs"]] == [
        ("run-1", 0.75),
        ("run-2", 5.0),
    ]


def test_a_period_that_ends_before_it_begins_is_refused() -> None:
    server = Server()
    answered = server.client.get(
        ROUTE,
        params={"since": NOW.isoformat(), "until": "2026-01-01T00:00:00"},
        headers=bearer(ADMINISTRATOR),
    )
    assert answered.status_code == 422
    assert "ends after it begins" in answered.json()["detail"]


def test_the_repository_page_needs_no_token() -> None:
    page = Server().client.get("/operations/repository")
    assert page.status_code == 200
    assert "<title>Repository spend</title>" in page.text
    assert '<script src="../sign-in.js"></script>' in page.text
