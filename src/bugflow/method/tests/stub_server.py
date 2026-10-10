"""A stub identity provider and a stub server behind one transport, for
tests of sending a deployment."""

import json
from typing import Any
from urllib.parse import parse_qs

import httpx2

ISSUER = "https://idp.example"
API = "https://bugflow.example"
#: The token the stub provider gives.
TOKEN = "token-1"


class StubServer:
    """Answers the provider's two routes and the server's one.

    It keeps each request for a token and each body posted to the
    server. The server answers ``status`` and ``body`` to every post.
    Left as they are, it answers as a server that put the files in
    force.
    """

    def __init__(self) -> None:
        self.token_status = 200
        self.status = 200
        self.body: Any = None
        self.token_requests: list[tuple[str, dict[str, list[str]]]] = []
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return httpx2.Response(
                200, json={"token_endpoint": f"{ISSUER}/oauth/v2/token"}
            )
        if url == f"{ISSUER}/oauth/v2/token":
            self.token_requests.append(
                (
                    request.headers.get("authorization", ""),
                    parse_qs(request.content.decode()),
                )
            )
            if self.token_status != 200:
                return httpx2.Response(
                    self.token_status, json={"error": "invalid_client"}
                )
            return httpx2.Response(200, json={"access_token": TOKEN})
        if url == f"{API}/api/policy-deployments":
            sent = json.loads(request.content)
            self.posts.append((request.headers.get("authorization", ""), sent))
            if self.status != 200:
                return httpx2.Response(self.status, json=self.body)
            return httpx2.Response(200, json=self.body or _deployed(sent))
        return httpx2.Response(404)


def _deployed(sent: dict[str, Any]) -> dict[str, Any]:
    """What a server answers when it puts the files in force, or checks
    them with nothing in force."""
    if sent["check_only"]:
        return {
            "outcome": "checked",
            "content_hash": "a" * 64,
            "in_force": None,
        }
    return {
        "outcome": "deployed",
        "content_hash": "a" * 64,
        "in_force": {
            "repository": sent["repository"],
            "commit": sent["commit"],
            "content_hash": "a" * 64,
        },
    }
