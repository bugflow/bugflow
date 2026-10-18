"""The MCP HTTP server authenticates before exchanging caller tokens."""

import time
from typing import Any

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from bugflow.apps.mcp import server
from bugflow.shared.domain.errors import TokenRefusedError

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def environment() -> dict[str, str]:
    return {
        "MCP_ISSUER": "https://issuer.example",
        "MCP_AUDIENCE": "mcp-project",
        "MCP_CLIENTS": "desktop, another-client",
        "MCP_ROLES_CLAIM": "roles",
        "MCP_EXCHANGE_CLIENT_ID": "exchange-client",
        "MCP_EXCHANGE_CLIENT_SECRET": "test-only-secret",
        "MCP_API_AUDIENCE": "api-project",
        "MCP_API_URL": "https://api.example",
        "MCP_PUBLIC_URL": "https://mcp.example",
    }


def token(**claims: Any) -> str:
    return jwt.encode(
        {
            "iss": "https://issuer.example",
            "aud": "mcp-project",
            "sub": "person-1",
            "client_id": "desktop",
            "exp": int(time.time()) + 600,
            "roles": [],
            **claims,
        },
        KEY,
        algorithm="RS256",
    )


class RefusingExchange:
    def __init__(self, *args: object) -> None:
        self.calls: list[str] = []
        self.closed = False

    def exchange(self, held: str) -> str:
        self.calls.append(held)
        raise TokenRefusedError("refused by the test exchange")

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def exchange(monkeypatch: pytest.MonkeyPatch) -> RefusingExchange:
    instance = RefusingExchange()
    instance.calls = []
    monkeypatch.setattr(server, "ZitadelTokenExchange", lambda *args: instance)
    return instance


def client() -> TestClient:
    return TestClient(
        server.mcp_from_environment(
            environment(), key=lambda _: KEY.public_key()
        ),
        base_url="https://mcp.example",
    )


@pytest.mark.parametrize("name", server.REQUIRED)
@pytest.mark.parametrize("value", [None, "", "   "])
def test_each_required_setting_must_be_supplied(
    name: str, value: str | None
) -> None:
    settings = environment()
    if value is None:
        del settings[name]
    else:
        settings[name] = value
    with pytest.raises(ValueError, match=name):
        server.mcp_from_environment(settings, key=lambda _: KEY.public_key())


def test_mcp_and_api_must_have_different_audiences() -> None:
    settings = environment() | {"MCP_API_AUDIENCE": "mcp-project"}
    with pytest.raises(ValueError, match="audiences must differ"):
        server.mcp_from_environment(settings, key=lambda _: KEY.public_key())


@pytest.mark.parametrize("name", ["MCP_API_URL", "MCP_PUBLIC_URL"])
@pytest.mark.parametrize(
    "value",
    [
        "not-a-url",
        "ftp://api.example",
        "https://user:password@api.example",
        "https://api.example/path",
        "https://api.example?query=yes",
        "https://api.example#fragment",
        "https://api.example:bad",
        "https://api.example:99999",
        "https://api.example/\\bad",
    ],
)
def test_malformed_origins_do_not_start_the_server(
    name: str, value: str
) -> None:
    with pytest.raises(ValueError, match=name):
        server.mcp_from_environment(
            environment() | {name: value}, key=lambda _: KEY.public_key()
        )


def test_an_empty_client_list_is_refused() -> None:
    with pytest.raises(ValueError, match="MCP_CLIENTS"):
        server.mcp_from_environment(
            environment() | {"MCP_CLIENTS": " , , "},
            key=lambda _: KEY.public_key(),
        )


def test_protected_resource_metadata_is_public(
    exchange: RefusingExchange,
) -> None:
    with client() as http:
        response = http.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    assert response.json()["resource"] == "https://mcp.example/mcp"
    assert response.json()["authorization_servers"] == [
        "https://issuer.example"
    ]
    assert {
        "urn:zitadel:iam:org:project:id:mcp-project:aud",
        "urn:zitadel:iam:org:project:id:api-project:aud",
    } <= set(response.json()["scopes_supported"])
    assert exchange.calls == []
    assert exchange.closed


CALL = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "read_evaluation_history",
        "arguments": {
            "forge": "github",
            "owner": "orchard",
            "repo": "pear-tree",
            "pr_numbers": [5],
        },
    },
}
ACCEPT = {"Accept": "application/json, text/event-stream"}


@pytest.mark.parametrize(
    "held",
    [
        None,
        "not-a-jwt",
        token(exp=1),
        token(aud="api-project"),
        token(client_id="unregistered"),
        token(iss="https://other.example"),
    ],
)
def test_missing_or_invalid_tokens_are_refused_before_exchange(
    held: str | None, exchange: RefusingExchange
) -> None:
    headers = (
        ACCEPT
        if held is None
        else ACCEPT | {"Authorization": f"Bearer {held}"}
    )
    with client() as http:
        response = http.post("/mcp", json=CALL, headers=headers)
    assert response.status_code == 401
    assert "Bearer" in response.headers["WWW-Authenticate"]
    assert exchange.calls == []


def test_verified_http_caller_reaches_exchange_with_the_original_token(
    exchange: RefusingExchange,
) -> None:
    held = token()
    with client() as http:
        response = http.post(
            "/mcp",
            json=CALL,
            headers=ACCEPT | {"Authorization": f"Bearer {held}"},
        )
    assert response.status_code == 200, response.text
    assert exchange.calls == [held]
    assert "token exchange did not preserve your identity" in response.text
    assert "test-only-secret" not in response.text
    assert exchange.closed


def test_authenticated_tool_listing_does_not_exchange_a_token(
    exchange: RefusingExchange,
) -> None:
    with client() as http:
        response = http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers=ACCEPT | {"Authorization": f"Bearer {token()}"},
        )
    assert response.status_code == 200, response.text
    assert "read_evaluation_history" in response.text
    assert "read_evaluation_detail" in response.text
    assert exchange.calls == []


@pytest.mark.parametrize(
    "changed",
    [
        {},
        {"sub": "another-person"},
        {"client_id": "desktop"},
        {"aud": "mcp-project"},
    ],
)
def test_exchanged_jwt_must_bind_the_original_subject_to_the_api_client(
    changed: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims = {"aud": "api-project", "client_id": "exchange-client"} | changed
    exchanged = token(**claims)
    exchanged_inputs: list[str] = []
    api_requests: list[httpx2.Request] = []

    class Exchange:
        def exchange(self, held: str) -> str:
            exchanged_inputs.append(held)
            return exchanged

        def close(self) -> None:
            pass

    def answer(request: httpx2.Request) -> httpx2.Response:
        api_requests.append(request)
        return httpx2.Response(200, json={"event_count": 17})

    api = httpx2.Client(
        base_url="https://api.example", transport=httpx2.MockTransport(answer)
    )
    monkeypatch.setattr(
        server, "ZitadelTokenExchange", lambda *args: Exchange()
    )
    monkeypatch.setattr(httpx2, "Client", lambda **kwargs: api)
    held = token()
    with client() as http:
        response = http.post(
            "/mcp",
            json=CALL,
            headers=ACCEPT | {"Authorization": f"Bearer {held}"},
        )
    assert response.status_code == 200, response.text
    assert exchanged_inputs == [held]
    if changed:
        assert api_requests == []
        assert "token exchange did not preserve your identity" in response.text
    else:
        assert len(api_requests) == 1
        assert (
            api_requests[0].headers["Authorization"] == f"Bearer {exchanged}"
        )
        assert api_requests[0].url.path == (
            "/api/repositories/github/orchard/pear-tree/evaluations"
        )
        assert api_requests[0].url.params["pr_number"] == "5"
        assert "event_count" in response.text
        assert "17" in response.text
    assert api.is_closed
