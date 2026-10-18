"""Token exchange forwards the caller identity without exposing credentials."""

import base64
import traceback
from urllib.parse import parse_qs

import httpx2
import pytest

from bugflow.shared.domain.errors import TokenRefusedError
from bugflow.shared.infrastructure.zitadel_token_exchange import (
    ACCESS_TOKEN,
    GRANT,
    JWT,
    ROLES_SCOPE,
    ZitadelTokenExchange,
)


def exchange(
    client: httpx2.Client, issuer: str = "https://identity.example"
) -> ZitadelTokenExchange:
    return ZitadelTokenExchange(
        issuer, "mcp-client", "client-secret", "api-project", client
    )


def test_each_call_exchanges_the_subject_token_for_the_api_audience() -> None:
    seen: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200, json={"access_token": f"api-token-{len(seen)}"}
        )

    with httpx2.Client(transport=httpx2.MockTransport(answer)) as client:
        service = exchange(client)
        assert service.exchange("person-token") == "api-token-1"
        assert service.exchange("person-token") == "api-token-2"
        service.close()
        assert not client.is_closed
    assert len(seen) == 2
    request = seen[0]
    assert str(request.url) == "https://identity.example/oauth/v2/token"
    assert (
        request.headers["authorization"]
        == "Basic " + base64.b64encode(b"mcp-client:client-secret").decode()
    )
    assert parse_qs(request.content.decode()) == {
        "grant_type": [GRANT],
        "subject_token": ["person-token"],
        "subject_token_type": [ACCESS_TOKEN],
        "requested_token_type": [JWT],
        "audience": ["api-project"],
        "scope": [
            f"openid {ROLES_SCOPE} "
            "urn:zitadel:iam:org:project:id:api-project:aud"
        ],
    }


@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 429, 500])
def test_upstream_errors_and_redirects_reveal_no_response_body(
    status: int,
) -> None:
    seen: list[str] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        seen.append(str(request.url))
        return httpx2.Response(
            status,
            text="person-token client-secret sensitive detail",
            headers={"Location": "https://elsewhere.example/steal"},
        )

    with (
        httpx2.Client(
            transport=httpx2.MockTransport(answer), follow_redirects=True
        ) as client,
        pytest.raises(TokenRefusedError) as caught,
    ):
        exchange(client).exchange("person-token")
    assert str(caught.value) == "the caller's token could not be exchanged"
    assert len(seen) == 1


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {},
        {"access_token": None},
        {"access_token": 12},
        {"access_token": ""},
        {"access_token": " \n"},
        {"access_token": "two tokens"},
    ],
)
def test_invalid_success_payloads_are_refused(body: object) -> None:
    with (
        httpx2.Client(
            transport=httpx2.MockTransport(
                lambda _: httpx2.Response(200, json=body)
            )
        ) as client,
        pytest.raises(TokenRefusedError),
    ):
        exchange(client).exchange("person-token")


def test_invalid_json_reveals_no_upstream_body() -> None:
    with (
        httpx2.Client(
            transport=httpx2.MockTransport(
                lambda _: httpx2.Response(200, text="sensitive-invalid-json")
            )
        ) as client,
        pytest.raises(TokenRefusedError) as caught,
    ):
        exchange(client).exchange("person-token")
    assert "sensitive-invalid-json" not in "".join(
        traceback.format_exception(caught.value)
    )


def test_network_failure_reveals_no_tokens_or_secret() -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError(
            "person-token client-secret", request=request
        )

    with (
        httpx2.Client(transport=httpx2.MockTransport(fail)) as client,
        pytest.raises(TokenRefusedError) as caught,
    ):
        exchange(client).exchange("person-token")
    rendered = "".join(traceback.format_exception(caught.value))
    assert "person-token client-secret" not in rendered
    assert str(caught.value) == "the caller's token could not be exchanged"


@pytest.mark.parametrize(
    "issuer",
    [
        "http://identity.example",
        "https://user:secret@identity.example",
        "https://identity.example?query=secret",
        "https://identity.example#fragment",
        "https://identity.example?",
        "https://identity.example#",
        "https://",
        "file:///tmp/token",
        "http://localhost.evil.example",
        "https://identity.example:bad",
        " https://identity.example",
        "https://identity.example\n",
    ],
)
def test_unsafe_or_malformed_issuer_urls_are_refused(issuer: str) -> None:
    with httpx2.Client() as client, pytest.raises(ValueError):
        exchange(client, issuer)


@pytest.mark.parametrize(
    "issuer",
    [
        "https://identity.example/tenant/",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://[::1]:8080",
    ],
)
def test_https_or_loopback_http_issuers_are_accepted(issuer: str) -> None:
    seen: list[str] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        seen.append(str(request.url))
        return httpx2.Response(200, json={"access_token": "api-token"})

    with httpx2.Client(transport=httpx2.MockTransport(answer)) as client:
        assert exchange(client, issuer).exchange("person-token") == "api-token"
    assert seen == [f"{issuer.rstrip('/')}/oauth/v2/token"]


def test_blank_subject_tokens_are_refused_before_contacting_the_issuer() -> (
    None
):
    def unread(request: httpx2.Request) -> httpx2.Response:
        pytest.fail("issuer contacted for an absent subject token")

    with httpx2.Client(transport=httpx2.MockTransport(unread)) as client:
        for token in ("", " ", "\n"):
            with pytest.raises(TokenRefusedError):
                exchange(client).exchange(token)


def test_the_adapter_closes_a_client_it_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned = httpx2.Client(
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(200, json={"access_token": "api-token"})
        )
    )
    monkeypatch.setattr(httpx2, "Client", lambda **_: owned)
    adapter = ZitadelTokenExchange(
        "https://identity.example", "client", "secret", "api"
    )
    adapter.close()
    assert owned.is_closed
