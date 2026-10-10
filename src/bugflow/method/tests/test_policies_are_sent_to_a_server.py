"""Tests of sending a policy repository's files to a server.

The use case is built over a real directory and the HTTP adapter. The
identity provider and the server are stubs behind the adapter's
transport.
"""

from pathlib import Path

import httpx2
import pytest

from bugflow.method.domain.errors import (
    PoliciesRefusedError,
    PolicyServerError,
)
from bugflow.method.dtos.send_policies import (
    DeploymentInForce,
    SendPoliciesRequest,
)
from bugflow.method.infrastructure.http_policy_server import (
    HttpPolicyServer,
    PipelineSignIn,
)
from bugflow.method.infrastructure.policy_directory import PolicyDirectory
from bugflow.method.tests.policy_files import READ, laid_out
from bugflow.method.tests.stub_server import API, ISSUER, TOKEN, StubServer
from bugflow.method.usecases.send_policies import SendPoliciesUseCase

REPOSITORY = "example-org/pull-request-policies"
SIGN_IN = PipelineSignIn(
    issuer=ISSUER,
    client_id="policies-pipeline",
    client_secret="s3cret",
    audience="project-1",
)


def use_case(
    directory: Path, transport: httpx2.BaseTransport
) -> SendPoliciesUseCase:
    return SendPoliciesUseCase(
        PolicyDirectory(directory),
        HttpPolicyServer(API, SIGN_IN, transport),
    )


def request(check_only: bool = False) -> SendPoliciesRequest:
    return SendPoliciesRequest(
        repository=REPOSITORY, commit="c1", check_only=check_only
    )


def test_the_files_a_server_reads_are_posted_with_the_token(
    tmp_path: Path,
) -> None:
    stub = StubServer()
    send = use_case(laid_out(tmp_path), stub.transport())
    answered = send.execute(request())
    ((authorization, sent),) = stub.posts
    assert authorization == f"Bearer {TOKEN}"
    assert sent == {
        "repository": REPOSITORY,
        "commit": "c1",
        "files": [
            {"path": path, "text": text} for path, text in sorted(READ.items())
        ],
        "check_only": False,
    }
    assert (answered.outcome, answered.files) == ("deployed", 4)
    assert answered.in_force == DeploymentInForce(
        repository=REPOSITORY, commit="c1", content_hash="a" * 64
    )


def test_it_signs_in_with_its_secret_and_asks_for_three_scopes(
    tmp_path: Path,
) -> None:
    stub = StubServer()
    use_case(laid_out(tmp_path), stub.transport()).execute(request())
    ((authorization, form),) = stub.token_requests
    assert authorization.startswith("Basic ")
    assert form["grant_type"] == ["client_credentials"]
    assert form["scope"] == [
        "openid urn:zitadel:iam:org:project:id:project-1:aud "
        "urn:zitadel:iam:org:projects:roles"
    ]


def test_a_check_is_asked_for_and_answers_what_is_in_force(
    tmp_path: Path,
) -> None:
    stub = StubServer()
    send = use_case(laid_out(tmp_path), stub.transport())
    answered = send.execute(request(check_only=True))
    assert stub.posts[0][1]["check_only"] is True
    assert (answered.outcome, answered.in_force) == ("checked", None)


@pytest.mark.parametrize("status", [409, 422])
def test_files_the_server_refuses_are_refused_with_its_reason(
    tmp_path: Path, status: int
) -> None:
    stub = StubServer()
    stub.status, stub.body = status, {"detail": "XX-01-example.md: no header"}
    send = use_case(laid_out(tmp_path), stub.transport())
    with pytest.raises(PoliciesRefusedError, match="no header"):
        send.execute(request())


def test_a_token_the_server_does_not_accept_says_what_to_check(
    tmp_path: Path,
) -> None:
    stub = StubServer()
    stub.status = 401
    send = use_case(laid_out(tmp_path), stub.transport())
    with pytest.raises(PolicyServerError, match="audience"):
        send.execute(request())


def test_a_client_without_the_role_is_told_which_role_it_needs(
    tmp_path: Path,
) -> None:
    stub = StubServer()
    stub.status = 403
    send = use_case(laid_out(tmp_path), stub.transport())
    with pytest.raises(PolicyServerError, match="bugflow-policy-deployer"):
        send.execute(request())


def test_any_other_answer_is_reported_with_its_status(tmp_path: Path) -> None:
    stub = StubServer()
    stub.status, stub.body = 500, {"detail": "the database is away"}
    send = use_case(laid_out(tmp_path), stub.transport())
    with pytest.raises(PolicyServerError, match="500: the database is away"):
        send.execute(request())


def test_an_answer_that_is_not_an_outcome_is_reported(tmp_path: Path) -> None:
    stub = StubServer()
    stub.body = {"outcome": "pending", "content_hash": "a" * 64}
    send = use_case(laid_out(tmp_path), stub.transport())
    with pytest.raises(PolicyServerError, match="could not be read"):
        send.execute(request())


def test_a_provider_that_refuses_the_secret_is_reported(
    tmp_path: Path,
) -> None:
    stub = StubServer()
    stub.token_status = 401
    send = use_case(laid_out(tmp_path), stub.transport())
    with pytest.raises(PolicyServerError, match=r"credentials \(401\)"):
        send.execute(request())
    assert stub.posts == []


def test_a_provider_that_cannot_be_reached_is_reported(
    tmp_path: Path,
) -> None:
    def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    send = use_case(laid_out(tmp_path), httpx2.MockTransport(unreachable))
    with pytest.raises(PolicyServerError, match="identity provider at"):
        send.execute(request())
