"""Tests that each set of routes serving a page serves what the page
loads: the stylesheet, the theme, the sign-in script and who a token
names.

A tenant's API may be built of some of the package's routes and not its
``create_api``; the pages it serves must still sign a person in.
"""

from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from bugflow.apps.api.operations import operations_routes
from bugflow.apps.api.settings import settings_routes
from bugflow.apps.api.tests.doubles import (
    ADMINISTRATOR,
    Server,
    Tokens,
    bearer,
)
from bugflow.shared.domain.values.caller import Caller

LOADED = ("/pages.css", "/theme.css", "/sign-in.js")


def caller(authorization: str = Header("")) -> Caller:
    return Tokens().verify(authorization.removeprefix("Bearer "))


def test_the_settings_routes_alone_serve_what_their_page_loads() -> None:
    app = FastAPI()
    settings_routes(app, caller, Server().administration)
    client = TestClient(app)

    assert client.get("/settings").status_code == 200
    for path in LOADED:
        assert client.get(path).status_code == 200, path
    assert client.get("/api/me", headers=bearer(ADMINISTRATOR)).json()[
        "roles"
    ] == [ADMINISTRATOR]


def test_the_operations_routes_alone_serve_what_their_pages_load() -> None:
    app = FastAPI()
    operations_routes(app, caller, Server().operations)
    client = TestClient(app)

    for path in LOADED:
        assert client.get(path).status_code == 200, path
    assert client.get("/api/me", headers=bearer("nobody")).status_code == 200


def test_two_sets_of_routes_serve_what_is_loaded_once() -> None:
    server = Server()
    app = FastAPI()
    settings_routes(app, caller, server.administration)
    operations_routes(app, caller, server.operations)

    paths = [getattr(one, "path", None) for one in app.routes]
    for path in (*LOADED, "/api/me"):
        assert paths.count(path) == 1, path
