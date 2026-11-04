"""Tests of the run route and page of the operations views, over
in-memory stores."""

import uuid
from datetime import UTC, datetime

from bugflow.apps.api.tests.doubles import (
    ADMINISTRATOR,
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
from bugflow.review.tests.payloads import whole
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.budget import Budget

WORKFLOW, RUN = "review/example-org/widgets/7", "run-1"
AT = datetime(2026, 10, 9, 11, 0, tzinfo=UTC)
RUN_ROUTE = f"/api/operations/runs/{RUN}?workflow_id={WORKFLOW}"


def ran(server: Server) -> JournalEntry:
    """A run that dispatched a reviewer, and its cost."""
    dispatched = JournalEntry(
        event_id=uuid.uuid4(),
        occurred_at=AT,
        event_type="agent.dispatched",
        forge="github",
        repo="example-org/widgets",
        pr_number=7,
        commit_sha=None,
        corpus_version=None,
        workflow_id=WORKFLOW,
        run_id=RUN,
        payload=whole(
            "agent.dispatched", step="collected", cost={"usd": 0.75}
        ),
        agent_id="safety",
    )
    server.journal.entries.append(dispatched)
    server.spend.recorded.append(
        RecordedCost(
            event_id=str(dispatched.event_id),
            workflow_id=WORKFLOW,
            run_id=RUN,
            forge="github",
            repo="example-org/widgets",
            agent_id="safety",
            kind="agent_dispatch",
            at=AT,
            usd=0.75,
        )
    )
    return dispatched


def test_a_run_needs_the_settings_role() -> None:
    server = Server()
    ran(server)
    assert server.client.get(RUN_ROUTE).status_code == 401
    assert (
        server.client.get(RUN_ROUTE, headers=bearer(READER)).status_code == 403
    )


def test_a_run_is_read_with_its_costs_allowances_and_activity() -> None:
    server = Server()
    dispatched = ran(server)
    server.ceilings.declare(
        SpendBinding(
            scope=SpendScope(forge="github", repo="example-org/widgets"),
            budget=Budget(usd=0.5),
        )
    )
    answered = server.client.get(RUN_ROUTE, headers=bearer(ADMINISTRATOR))
    assert answered.status_code == 200
    held = answered.json()
    assert (held["repo"], held["spent_usd"]) == ("example-org/widgets", 0.75)
    assert [(one["kind"], one["event_id"]) for one in held["costs"]] == [
        ("agent_dispatch", str(dispatched.event_id))
    ]
    (allowance,) = held["allowances"]
    assert {
        key: allowance[key]
        for key in ("per", "allowed_usd", "spent_usd", "left_usd", "has_room")
    } == {
        "per": "event",
        "allowed_usd": 0.5,
        "spent_usd": 0.75,
        "left_usd": 0.0,
        "has_room": False,
    }
    assert allowance["over_usd"] == 0.25
    assert [one["event_type"] for one in held["activity"]] == [
        "agent.dispatched"
    ]


def test_a_run_the_journal_does_not_hold_is_not_found() -> None:
    server = Server()
    answered = server.client.get(RUN_ROUTE, headers=bearer(ADMINISTRATOR))
    assert answered.status_code == 404


def test_the_run_page_needs_no_token() -> None:
    server = Server()
    page = server.client.get("/operations/run")
    assert page.status_code == 200
    assert "<title>Run spend</title>" in page.text
    assert '<script src="../sign-in.js"></script>' in page.text


def test_every_page_loads_the_script_and_style_the_pages_share() -> None:
    server = Server()
    for page in ("/operations/run", "/operations/repository"):
        text = server.client.get(page).text
        assert '<script src="pages.js"></script>' in text
        assert '<link rel="stylesheet" href="pages.css">' in text
    script = server.client.get("/operations/pages.js")
    assert script.headers["content-type"].startswith("text/javascript")
    assert "function renderAllowances(" in script.text
    style = server.client.get("/operations/pages.css")
    assert style.headers["content-type"].startswith("text/css")
