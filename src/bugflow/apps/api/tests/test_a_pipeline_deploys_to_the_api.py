"""``bugflow deploy-policies``, what a policy repository's pipeline runs,
against the real API: it signs in to the identity provider and posts a
directory's files to the server.

The identity provider is a stub. The server is the real API, built over
in-memory stores, and the command's requests are handed to it.
"""

from pathlib import Path
from urllib.parse import parse_qs

import httpx2
import pytest

from bugflow.apps.api.tests.doubles import DEPLOYER, READER, Server
from bugflow.apps.command.command import run
from bugflow.method.tests.policy_files import laid_out

REPOSITORY = "example-org/pull-request-policies"
ISSUER = "https://idp.example"
API = "https://bugflow.example"
ENVIRON = {
    "POLICY_DEPLOY_ISSUER": ISSUER,
    "POLICY_DEPLOY_CLIENT_ID": "policies-pipeline",
    "POLICY_DEPLOY_CLIENT_SECRET": "s3cret",
    "POLICY_DEPLOY_AUDIENCE": "project-1",
}


class Provider:
    """A stub identity provider in front of the real API, behind one
    transport. The token it gives is ``role``, which the server's token
    check reads as the caller's one role."""

    def __init__(self, role: str = DEPLOYER) -> None:
        self.role = role
        self.server = Server()
        self.token_requests: list[tuple[str, dict[str, list[str]]]] = []

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
            return httpx2.Response(200, json={"access_token": self.role})
        if url.startswith(API):
            answered = self.server.client.request(
                request.method,
                url.removeprefix(API),
                content=request.content,
                headers=dict(request.headers),
            )
            return httpx2.Response(
                answered.status_code, content=answered.content
            )
        return httpx2.Response(404)

    def run(
        self, directory: Path, commit: str = "c1", check_only: bool = False
    ) -> int:
        return run(
            [
                "deploy-policies",
                str(directory),
                "--repository",
                REPOSITORY,
                "--commit",
                commit,
                "--api",
                API,
                *(["--check"] if check_only else []),
            ],
            environ=ENVIRON,
            transport=httpx2.MockTransport(self.handle),
        )


def test_the_pipeline_deploys_a_directory_to_the_server(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = Provider()
    assert provider.run(laid_out(tmp_path)) == 0
    in_force = provider.server.deployments.in_force()
    assert in_force is not None
    assert (in_force.repository, in_force.commit) == (REPOSITORY, "c1")
    assert len(in_force.files) == 4
    said = capsys.readouterr().out
    assert said.startswith("deployed 4 files, content ")
    assert f"in force: {REPOSITORY} at c1" in said
    (fact,) = provider.server.journal.entries
    assert (
        fact.payload["sent_by"] == "machine-user-1 through policies-pipeline"
    )


def test_it_signs_in_with_its_secret_as_a_client() -> None:
    provider = Provider()
    provider.run(Path(__file__).parent)
    (authorization, form) = provider.token_requests[0]
    assert authorization.startswith("Basic ")
    assert form["grant_type"] == ["client_credentials"]


def test_running_it_again_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = Provider()
    provider.run(laid_out(tmp_path))
    capsys.readouterr()
    assert provider.run(tmp_path) == 0
    assert capsys.readouterr().out.startswith(
        "already in force, nothing changed"
    )
    assert len(provider.server.journal.entries) == 1


def test_a_check_stores_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = Provider()
    assert provider.run(laid_out(tmp_path), check_only=True) == 0
    assert provider.server.deployments.in_force() is None
    said = capsys.readouterr().out
    assert said.startswith("checked 4 files")
    assert "nothing stored; in force: nothing" in said


def test_files_the_server_refuses_fail_the_pipeline_with_the_reasons(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = Provider()
    laid_out(tmp_path)
    (tmp_path / "prose/policies/P-01-example.md").write_text("broken\n")
    assert provider.run(tmp_path, check_only=True) == 1
    assert "P-01-example.md" in capsys.readouterr().err


def test_a_commit_held_with_other_content_fails_the_pipeline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = Provider()
    provider.run(laid_out(tmp_path))
    (tmp_path / "prose/doctrine/01-voice.md").write_text("Changed.\n")
    assert provider.run(tmp_path) == 1
    assert "already held with other content" in capsys.readouterr().err


def test_a_client_without_the_role_fails_the_pipeline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = Provider(role=READER)
    assert provider.run(laid_out(tmp_path)) == 2
    assert capsys.readouterr().err.startswith("error: ")
    assert provider.server.deployments.in_force() is None


def test_a_token_the_server_does_not_accept_fails_the_pipeline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = Provider(role="refused")
    assert provider.run(laid_out(tmp_path)) == 2
    assert capsys.readouterr().err.startswith("error: ")
    assert provider.server.deployments.in_force() is None
