"""Tests of reading and changing a scope's allowances through the
operations routes, over in-memory stores."""

from bugflow.apps.api.tests.doubles import (
    ADMINISTRATOR,
    READER,
    Server,
    bearer,
)
from bugflow.review.domain.facts import ALLOWANCE_DECLARED
from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.shared.domain.values.budget import Budget

ROUTE = "/api/operations/allowances"
WIDGETS = {"forge": "github", "repo": "example-org/widgets"}
SAFETY = {**WIDGETS, "agent_id": "safety"}


def scope(**parts: str) -> dict[str, str]:
    return {
        "forge": "",
        "owner": "",
        "repo": "",
        "layer": "",
        "agent_id": "",
        **parts,
    }


def test_allowances_need_the_settings_role() -> None:
    server = Server()
    assert server.client.get(ROUTE).status_code == 401
    for method in ("get", "delete"):
        answered = getattr(server.client, method)(
            ROUTE, params={"per": "event"}, headers=bearer(READER)
        )
        assert answered.status_code == 403
    answered = server.client.put(
        ROUTE,
        json={"scope": scope(), "per": "event", "usd": 1, "turns": None},
        headers=bearer(READER),
    )
    assert answered.status_code == 403


def test_a_scope_reads_what_it_inherits_and_where_its_ceiling_comes_from() -> (
    None
):
    server = Server()
    server.ceilings.declare(
        SpendBinding(
            scope=SpendScope(forge="github", repo="example-org/widgets"),
            budget=Budget(usd=5.0, turns=40),
        )
    )
    server.ceilings.declare(
        SpendBinding(
            scope=SpendScope(agent_id="safety"),
            budget=Budget(usd=1.0, turns=None),
        )
    )
    held = server.client.get(
        ROUTE, params=SAFETY, headers=bearer(ADMINISTRATOR)
    ).json()
    assert held["scope"] == scope(**SAFETY)
    assert held["cadences"] == ["event", "week"]
    assert [
        (one["scope"]["agent_id"], one["own"]) for one in held["applied"]
    ] == [
        ("", False),
        ("safety", False),
    ]
    ceiling = held["ceiling"]
    assert (ceiling["usd"], ceiling["usd_from"]["scope"]) == (
        1.0,
        scope(agent_id="safety"),
    )
    assert (ceiling["turns"], ceiling["turns_from"]["scope"]) == (
        40,
        scope(**WIDGETS),
    )


def test_declaring_an_allowance_journals_who_declared_it() -> None:
    server = Server()
    answered = server.client.put(
        ROUTE,
        json={
            "scope": scope(**SAFETY),
            "per": "week",
            "usd": 3.0,
            "turns": None,
        },
        headers=bearer(ADMINISTRATOR),
    )
    assert answered.status_code == 200
    (own,) = answered.json()["applied"]
    assert (own["per"], own["allowed_usd"], own["own"]) == ("week", 3.0, True)
    (entry,) = [
        one
        for one in server.journal.entries
        if one.event_type == ALLOWANCE_DECLARED
    ]
    assert entry.payload["declared_by"] == "machine-user-1"
    assert entry.payload["usd"] == 3.0


def test_revoking_leaves_the_scope_to_what_covers_it() -> None:
    server = Server()
    for body_scope, usd in ((scope(**SAFETY), 1.0), (scope(**WIDGETS), 5.0)):
        server.client.put(
            ROUTE,
            json={
                "scope": body_scope,
                "per": "event",
                "usd": usd,
                "turns": None,
            },
            headers=bearer(ADMINISTRATOR),
        )
    answered = server.client.delete(
        ROUTE, params={**SAFETY, "per": "event"}, headers=bearer(ADMINISTRATOR)
    )
    held = answered.json()
    assert [
        (one["scope"]["agent_id"], one["own"]) for one in held["applied"]
    ] == [("", False)]
    assert held["ceiling"]["usd"] == 5.0


def test_a_declaration_the_server_cannot_hold_is_refused() -> None:
    server = Server()
    for body, says in (
        (
            {"scope": scope(**WIDGETS), "per": "fortnightly", "usd": 1},
            "not a cadence",
        ),
        (
            {"scope": scope(**WIDGETS), "per": "event", "usd": -1},
            "not below zero",
        ),
        (
            {"scope": scope(repo="example-org/widgets"), "per": "event"},
            "names its forge",
        ),
        (
            {
                "scope": scope(
                    forge="github", owner="example-org", repo="example-org/w"
                ),
                "per": "event",
            },
            "not both",
        ),
    ):
        answered = server.client.put(
            ROUTE,
            json={"usd": None, "turns": None, **body},
            headers=bearer(ADMINISTRATOR),
        )
        assert answered.status_code == 422
        assert says in answered.json()["detail"]
    assert server.ceilings.bindings() == []


def test_the_allowances_page_needs_no_token() -> None:
    page = Server().client.get("/operations/allowances")
    assert page.status_code == 200
    assert "<title>Allowances</title>" in page.text
    assert '<script src="pages.js"></script>' in page.text
