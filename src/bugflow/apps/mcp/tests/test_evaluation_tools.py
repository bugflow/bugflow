"""MCP tools relay the real HTTP API response under the exchanged identity."""

import asyncio
import json
from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import LATEST_PROTOCOL_VERSION, CallToolResult, TextContent

from bugflow.apps.api.api import PolicyDeploying, create_api
from bugflow.apps.api.evaluations import EvaluationReading
from bugflow.apps.api.role_policy_deployment_access import (
    RolePolicyDeploymentAccess,
)
from bugflow.apps.api.tests.doubles import DEPLOYER, Server
from bugflow.apps.api.tests.test_reading_evaluations import (
    DETAIL,
    HISTORY,
    REF,
    RUN,
    SELECTOR,
    CountedHistory,
    fact,
)
from bugflow.apps.mcp.server import build_mcp
from bugflow.apps.mcp.tools import EvaluationTools
from bugflow.apps.shared.submission_source import ForgeBoundedSubmissionSource
from bugflow.forge.domain.models.pull_request import PullRequestSnapshot
from bugflow.forge.infrastructure.in_memory_snapshots import (
    InMemorySnapshotStore,
)
from bugflow.review.domain.models.history import HistoryLimits
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.review.infrastructure.in_memory_judge_archive import (
    InMemoryJudgeArchive,
)
from bugflow.review.usecases.read_review_record import (
    ReadReviewHistoryUseCase,
    ReadReviewRecordUseCase,
)
from bugflow.shared.domain.errors import TokenRefusedError
from bugflow.shared.domain.values.caller import Caller
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

ISSUER = "https://identity.example"
PUBLIC = "https://mcp.example"
SCOPES = ["openid", "evaluation-read"]
HISTORY_TOOL = "read_evaluation_history"
DETAIL_TOOL = "read_evaluation_detail"
REPOSITORY = {"forge": "github", "owner": "orchard", "repo": "pear-tree"}
HISTORY_ARGS: dict[str, Any] = REPOSITORY | {
    "pr_numbers": [6, 5, 5],
    "policy_id": "ED-02",
}
DETAIL_ARGS: dict[str, Any] = REPOSITORY | {"pr_number": 5, **SELECTOR}


class Tokens:
    def __init__(self, values: dict[str, Caller]) -> None:
        self.values = values.copy()
        self.checked: list[str] = []

    def verify(self, token: str) -> Caller:
        self.checked.append(token)
        if token not in self.values:
            raise TokenRefusedError("not issued by this test")
        return self.values[token]


class Exchange:
    def __init__(self) -> None:
        self.values = {"person": "api-person", "outsider": "api-outsider"}
        self.received: list[str] = []

    def exchange(self, token: str) -> str:
        self.received.append(token)
        if token not in self.values:
            raise TokenRefusedError("exchange refused")
        return self.values[token]


class Access:
    def may_read(self, caller: Caller, ref: PullRequestRef) -> bool:
        return caller.subject == "subject" and ref in (
            REF,
            replace(REF, number=6),
        )


class Relay:
    def __init__(self, limits: HistoryLimits | None = None) -> None:
        self.incoming = Tokens(
            {
                "person": Caller("subject", "agent", frozenset()),
                "outsider": Caller("outsider", "agent", frozenset()),
            }
        )
        accepted = {
            "api-person": Caller("subject", "relay", frozenset()),
            "api-outsider": Caller("outsider", "relay", frozenset()),
        }
        self.api_tokens, self.api_check = Tokens(accepted), Tokens(accepted)
        self.exchange = Exchange()
        archive = InMemoryJudgeArchive()
        self.exchange_id = archive.put(
            JudgeExchange(
                request={"prompt": "retained prompt"},
                response={"answer": "retained"},
            )
        )
        snapshots = InMemorySnapshotStore()
        self.snapshot_id = snapshots.put(
            PullRequestSnapshot(
                ref=REF,
                title="Title",
                body="retained submission",
                head_branch="change",
                base_branch="main",
                commits=(),
                files=(),
            )
        ).snapshot_id
        self.history = CountedHistory(
            [
                fact(payload={"snapshot_id": self.snapshot_id}),
                fact(
                    "judge.invoked",
                    payload={
                        "policy_id": "ED-02",
                        "status": "judged",
                        "identity": {"exchange_id": self.exchange_id},
                    },
                ),
                fact(
                    "llm.called",
                    payload={
                        "call_id": "call-one",
                        "policy_id": "ED-02",
                        "cost_nanodollars": 7,
                    },
                ),
                fact(
                    "judge.invoked",
                    run=replace(RUN, run_id="other-run"),
                    payload={
                        "policy_id": "ED-02",
                        "status": "unavailable",
                        "identity": {"exchange_id": "missing-exchange"},
                    },
                ),
            ]
        )
        app = create_api(
            self.api_tokens,
            PolicyDeploying(
                RolePolicyDeploymentAccess(DEPLOYER), Server().deploying
            ),
            EvaluationReading(
                Access(),
                ReadReviewHistoryUseCase(self.history, limits),
                ReadReviewRecordUseCase(
                    self.history,
                    archive,
                    ForgeBoundedSubmissionSource(snapshots),
                    limits,
                ),
            ),
        )
        self.api = TestClient(app)
        self.requests: list[httpx2.Request] = []

        def answer(request: httpx2.Request) -> httpx2.Response:
            self.requests.append(request)
            response = self.api.request(
                request.method,
                request.url.raw_path.decode(),
                headers=dict(request.headers),
            )
            return httpx2.Response(
                response.status_code,
                content=response.content,
                headers=dict(response.headers),
            )

        self.client = httpx2.Client(
            base_url="https://api.example",
            transport=httpx2.MockTransport(answer),
        )
        self.tools = EvaluationTools(
            self.client, self.exchange, self.api_check
        )
        self.server = build_mcp(
            self.tools, self.incoming, ISSUER, "mcp-audience", PUBLIC, SCOPES
        )

    def close(self) -> None:
        self.client.close()
        self.api.close()

    def call(
        self, name: str, arguments: dict[str, Any], person: str = "person"
    ) -> str:
        caller = self.incoming.values[person]
        held = auth_context_var.set(
            AuthenticatedUser(
                AccessToken(
                    token=person,
                    client_id=caller.client,
                    subject=caller.subject,
                    scopes=SCOPES,
                )
            )
        )
        try:
            result = asyncio.run(self.server.call_tool(name, arguments))
        finally:
            auth_context_var.reset(held)
        assert isinstance(result, CallToolResult)
        assert result.structured_content is None
        assert len(result.content) == 1
        block = result.content[0]
        assert isinstance(block, TextContent)
        return block.text


@pytest.fixture
def make_relay() -> Iterator[Callable[..., Relay]]:
    relays: list[Relay] = []

    def make(limits: HistoryLimits | None = None) -> Relay:
        relay = Relay(limits)
        relays.append(relay)
        return relay

    yield make
    for relay in relays:
        relay.close()


def test_history_matches_the_api_json_with_costs_and_coverage(
    make_relay: Callable[..., Relay],
) -> None:
    relay = make_relay()
    expected = relay.api.get(
        HISTORY,
        params=[
            ("pr_number", 6),
            ("pr_number", 5),
            ("pr_number", 5),
            ("policy_id", "ED-02"),
        ],
        headers={"Authorization": "Bearer api-person"},
    )
    received = relay.call(HISTORY_TOOL, HISTORY_ARGS)
    assert received == expected.text
    parsed = json.loads(received)
    assert parsed["unobserved_pr_numbers"] == [6]
    assert len(parsed["runs"]) == 2
    assert sum(run["model_cost"]["nanodollars"] for run in parsed["runs"]) == 7
    assert all(
        run["requested_policy_cost"] is not None for run in parsed["runs"]
    )


@pytest.mark.parametrize("run_id", [RUN.run_id, "other-run"])
def test_detail_matches_the_api_with_available_and_missing_content(
    make_relay: Callable[..., Relay],
    run_id: str,
) -> None:
    relay = make_relay()
    expected = relay.api.get(
        DETAIL,
        params=SELECTOR | {"run_id": run_id},
        headers={"Authorization": "Bearer api-person"},
    )
    received = relay.call(DETAIL_TOOL, DETAIL_ARGS | {"run_id": run_id})
    assert received == expected.text
    parsed = json.loads(received)
    if run_id == RUN.run_id:
        assert (
            parsed["submissions"][relay.snapshot_id]["body"]
            == "retained submission"
        )
        assert parsed["record"]["policies"][0]["exchange"]["response"] == {
            "answer": "retained"
        }
    else:
        assert parsed["missing_exchanges"] == ["missing-exchange"]


def test_each_call_exchanges_and_the_api_checks_only_the_exchanged_token(
    make_relay: Callable[..., Relay],
) -> None:
    relay = make_relay()
    relay.call(HISTORY_TOOL, HISTORY_ARGS)
    relay.call(DETAIL_TOOL, DETAIL_ARGS)
    assert relay.exchange.received == ["person", "person"]
    assert (
        relay.api_check.checked
        == relay.api_tokens.checked
        == ["api-person", "api-person"]
    )
    assert [r.headers["Authorization"] for r in relay.requests] == [
        "Bearer api-person",
        "Bearer api-person",
    ]


@pytest.mark.parametrize("failure", ["exchange", "verification", "subject"])
def test_failed_exchange_or_changed_subject_never_reaches_the_api(
    make_relay: Callable[..., Relay],
    failure: str,
) -> None:
    relay = make_relay()
    if failure == "exchange":
        relay.exchange.values.clear()
    elif failure == "verification":
        relay.api_check.values.clear()
    else:
        relay.api_check.values["api-person"] = Caller(
            "other", "relay", frozenset()
        )
    with pytest.raises(ToolError, match="identity"):
        relay.call(HISTORY_TOOL, HISTORY_ARGS)
    assert relay.requests == []
    assert relay.history.reads == 0


def test_the_api_independently_refuses_an_exchanged_token(
    make_relay: Callable[..., Relay],
) -> None:
    relay = make_relay()
    relay.api_tokens.values.clear()
    with pytest.raises(ToolError, match="API refused the exchanged token"):
        relay.call(HISTORY_TOOL, HISTORY_ARGS)
    assert len(relay.requests) == 1
    assert relay.history.reads == 0


@pytest.mark.parametrize("status", [403, 404, 413, 422])
def test_api_refusals_are_tool_errors_without_partial_evidence(
    make_relay: Callable[..., Relay],
    status: int,
) -> None:
    relay = make_relay(HistoryLimits(max_events=1) if status == 413 else None)
    name, args, person = HISTORY_TOOL, HISTORY_ARGS, "person"
    if status == 403:
        person = "outsider"
        message = "may not read"
    elif status == 404:
        name, args = DETAIL_TOOL, DETAIL_ARGS | {"run_id": "absent"}
        message = "no evaluation"
    elif status == 413:
        message = "exceeds"
    else:
        args = HISTORY_ARGS | {"policy_id": ""}
        message = "selectors"
    with pytest.raises(ToolError, match=message):
        relay.call(name, args, person)
    assert len(relay.requests) == 1
    if status in (403, 422):
        assert relay.history.reads == 0


def test_no_authentication_context_cannot_exchange_or_read(
    make_relay: Callable[..., Relay],
) -> None:
    relay = make_relay()
    with pytest.raises(ToolError, match="verified caller"):
        asyncio.run(relay.server.call_tool(HISTORY_TOOL, HISTORY_ARGS))
    assert relay.exchange.received == []
    assert relay.requests == []


def test_tool_schemas_expose_selectors_without_token_or_subject_inputs(
    make_relay: Callable[..., Relay],
) -> None:
    relay = make_relay()
    listed = {
        tool.name: tool for tool in asyncio.run(relay.server.list_tools())
    }
    assert set(listed) == {HISTORY_TOOL, DETAIL_TOOL}
    assert set(listed[HISTORY_TOOL].input_schema["properties"]) == {
        "forge",
        "owner",
        "repo",
        "pr_numbers",
        "policy_id",
    }
    assert set(listed[DETAIL_TOOL].input_schema["properties"]) == {
        "forge",
        "owner",
        "repo",
        "pr_number",
        "workflow_id",
        "run_id",
    }


def test_sdk_http_authentication_and_protected_resource_metadata(
    make_relay: Callable[..., Relay],
) -> None:
    relay = make_relay()
    app = relay.server.streamable_http_app(
        host="mcp.example", stateless_http=True
    )
    with TestClient(app, base_url=PUBLIC) as client:
        for headers in ({}, {"Authorization": "Bearer refused"}):
            response = client.post("/mcp", json={}, headers=headers)
            assert response.status_code == 401
            assert "resource_metadata" in response.headers["WWW-Authenticate"]
        metadata = client.get("/.well-known/oauth-protected-resource/mcp")
        assert metadata.status_code == 200
        assert metadata.json()["authorization_servers"] == [ISSUER]
        assert metadata.json()["scopes_supported"] == SCOPES
    assert relay.requests == []
    assert relay.exchange.received == []


def test_an_authenticated_sdk_http_call_reaches_the_api_as_the_same_person(
    make_relay: Callable[..., Relay],
) -> None:
    relay = make_relay()
    app = relay.server.streamable_http_app(
        host="mcp.example", stateless_http=True, json_response=True
    )
    headers = {
        "Authorization": "Bearer person",
        "Accept": "application/json, text/event-stream",
    }
    with TestClient(app, base_url=PUBLIC) as client:
        initialized = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": LATEST_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200, initialized.text
        headers["MCP-Protocol-Version"] = initialized.json()["result"][
            "protocolVersion"
        ]
        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": HISTORY_TOOL, "arguments": HISTORY_ARGS},
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert not result.get("isError")
        assert len(result["content"]) == 1
        assert json.loads(result["content"][0]["text"])["event_count"] == 4
    assert relay.incoming.checked == ["person", "person"]
    assert (
        relay.api_check.checked == relay.api_tokens.checked == ["api-person"]
    )
    assert relay.exchange.received == ["person"]


@pytest.mark.parametrize("status", [302, 307, 308])
def test_redirects_cannot_send_the_exchanged_token_to_another_destination(
    make_relay: Callable[..., Relay], status: int
) -> None:
    relay = make_relay()
    requests: list[httpx2.Request] = []

    def redirect(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            status, headers={"Location": "https://elsewhere.example/private"}
        )

    # The tool must override even a client configured to follow redirects.
    with httpx2.Client(
        base_url="https://api.example",
        transport=httpx2.MockTransport(redirect),
        follow_redirects=True,
    ) as client:
        tools = EvaluationTools(client, relay.exchange, relay.api_check)
        with pytest.raises(ToolError, match=f"answered {status}"):
            tools.history(
                "person", "subject", "github", "orchard", "pear-tree", [5]
            )
    assert len(requests) == 1
    assert requests[0].url.host == "api.example"
    assert requests[0].headers["Authorization"] == "Bearer api-person"


@pytest.mark.parametrize(
    "name,arguments",
    [
        (HISTORY_TOOL, HISTORY_ARGS),
        (DETAIL_TOOL, DETAIL_ARGS),
    ],
)
@pytest.mark.parametrize(
    "changed",
    [
        {"owner": ".."},
        {"owner": "../private"},
        {"owner": "%2e%2e"},
        {"repo": "other/repo"},
        {"repo": "https://elsewhere.example"},
        {"repo": "repo?secret=yes"},
        {"repo": "repo\\other"},
        {"forge": "unsupported"},
    ],
)
def test_invalid_paths_are_refused_before_exchange_or_http(
    make_relay: Callable[..., Relay],
    name: str,
    arguments: dict[str, Any],
    changed: dict[str, str],
) -> None:
    relay = make_relay()
    with pytest.raises(ToolError):
        relay.call(name, arguments | changed)
    assert relay.exchange.received == []
    assert relay.requests == []
    assert relay.api_check.checked == []
