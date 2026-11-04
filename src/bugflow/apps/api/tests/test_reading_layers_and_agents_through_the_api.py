"""Tests of the layer and agent routes and pages of the operations
views, over in-memory stores."""

from datetime import timedelta

import pytest

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


def spent(server: Server) -> None:
    """A reviewer's session and a judge's calls on two repositories."""
    for run, repo, layer, agent, usd in (
        ("run-1", "example-org/widgets", "service", "safety", 0.75),
        ("run-1", "example-org/widgets", "", "", 0.25),
        ("run-2", "example-org/gadgets", "service", "safety", 0.5),
    ):
        server.spend.recorded.append(
            RecordedCost(
                workflow_id=f"review/{repo}/7",
                run_id=run,
                forge="github",
                repo=repo,
                layer=layer,
                agent_id=agent,
                kind="agent_dispatch" if agent else "model_call",
                at=NOW - timedelta(hours=1),
                usd=usd,
            )
        )


@pytest.mark.parametrize(
    "route", ["/api/operations/layers", "/api/operations/agents"]
)
def test_layers_and_agents_need_the_settings_role(route: str) -> None:
    server = Server()
    assert server.client.get(route).status_code == 401
    assert server.client.get(route, headers=bearer(READER)).status_code == 403


def test_every_layer_is_read_by_repository_without_its_runs() -> None:
    server = Server()
    spent(server)
    held = server.client.get(
        "/api/operations/layers", headers=bearer(ADMINISTRATOR)
    ).json()
    assert (held["by"], held["name"], held["spent_usd"]) == (
        "layer",
        None,
        1.5,
    )
    assert [(one["repo"], one["layer"]) for one in held["cells"]] == [
        ("example-org/widgets", "service"),
        ("example-org/gadgets", "service"),
        ("example-org/widgets", ""),
    ]
    assert held["runs"] == []


def test_one_agent_is_read_with_its_allowances_and_runs() -> None:
    server = Server()
    spent(server)
    server.ceilings.declare(
        SpendBinding(
            scope=SpendScope(agent_id="safety"), budget=Budget(usd=1.0)
        )
    )
    held = server.client.get(
        "/api/operations/agents",
        params={"agent_id": "safety"},
        headers=bearer(ADMINISTRATOR),
    ).json()
    assert (held["by"], held["name"], held["spent_usd"]) == (
        "agent",
        "safety",
        1.25,
    )
    assert [one["scope"]["agent_id"] for one in held["allowances"]] == [
        "safety"
    ]
    # Runs as late as each other are listed by workflow and run.
    assert [(one["run_id"], one["repo"]) for one in held["runs"]] == [
        ("run-2", "example-org/gadgets"),
        ("run-1", "example-org/widgets"),
    ]


def test_an_empty_agent_reads_the_facts_that_name_none() -> None:
    server = Server()
    spent(server)
    held = server.client.get(
        "/api/operations/agents",
        params={"agent_id": ""},
        headers=bearer(ADMINISTRATOR),
    ).json()
    assert (held["name"], held["spent_usd"]) == ("", 0.25)


@pytest.mark.parametrize(
    ("page", "title", "route"),
    [
        ("/operations/layers", "Spend by layer", "api/operations/layers"),
        ("/operations/layer", "Spend of one layer", "api/operations/layers"),
        ("/operations/agents", "Spend by agent", "api/operations/agents"),
        ("/operations/agent", "Spend of one agent", "api/operations/agents"),
    ],
)
def test_each_layer_and_agent_page_reads_its_own_route(
    page: str, title: str, route: str
) -> None:
    answered = Server().client.get(page)
    assert answered.status_code == 200
    assert f"<title>{title}</title>" in answered.text
    assert f'"{route}?' in answered.text
    assert "__BY__" not in answered.text
    assert "__EVERY__" not in answered.text
