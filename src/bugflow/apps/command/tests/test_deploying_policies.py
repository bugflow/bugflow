"""Tests of ``bugflow deploy-policies``, run by its command line.

The identity provider and the server are stubs. The tests check what
the command prints and the status it exits with, which is what a
pipeline acts on.
"""

from pathlib import Path

import pytest

from bugflow.apps.command.command import run
from bugflow.method.tests.policy_files import laid_out
from bugflow.method.tests.stub_server import API, ISSUER, StubServer

REPOSITORY = "example-org/pull-request-policies"
ENVIRON = {
    "POLICY_DEPLOY_ISSUER": ISSUER,
    "POLICY_DEPLOY_CLIENT_ID": "policies-pipeline",
    "POLICY_DEPLOY_CLIENT_SECRET": "s3cret",
    "POLICY_DEPLOY_AUDIENCE": "project-1",
}


def deploy(
    stub: StubServer,
    directory: Path,
    *flags: str,
    environ: dict[str, str] | None = None,
) -> int:
    return run(
        [
            "deploy-policies",
            str(directory),
            "--repository",
            REPOSITORY,
            "--commit",
            "c1",
            "--api",
            API,
            *flags,
        ],
        environ=ENVIRON if environ is None else environ,
        transport=stub.transport(),
    )


def test_a_directory_is_deployed_and_what_is_in_force_is_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stub = StubServer()
    assert deploy(stub, laid_out(tmp_path)) == 0
    assert capsys.readouterr().out == (
        "deployed 4 files, content aaaaaaaaaaaa; "
        f"in force: {REPOSITORY} at c1, content aaaaaaaaaaaa\n"
    )


def test_a_deployment_already_in_force_is_said_to_change_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stub = StubServer()
    stub.body = {
        "outcome": "already_in_force",
        "content_hash": "a" * 64,
        "in_force": {
            "repository": REPOSITORY,
            "commit": "c1",
            "content_hash": "a" * 64,
        },
    }
    assert deploy(stub, laid_out(tmp_path)) == 0
    assert capsys.readouterr().out.startswith(
        "already in force, nothing changed: "
    )


def test_a_check_says_nothing_was_stored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stub = StubServer()
    assert deploy(stub, laid_out(tmp_path), "--check") == 0
    assert stub.posts[0][1]["check_only"] is True
    assert capsys.readouterr().out == (
        "checked 4 files, content aaaaaaaaaaaa, nothing stored; "
        "in force: nothing\n"
    )


def test_files_the_server_refuses_exit_1_with_its_reasons(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stub = StubServer()
    stub.status, stub.body = 422, {"detail": "XX-01-example.md: no header"}
    assert deploy(stub, laid_out(tmp_path), "--check") == 1
    assert capsys.readouterr().err == (
        "refused: XX-01-example.md: no header\n"
    )


def test_a_client_that_may_not_deploy_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stub = StubServer()
    stub.status = 403
    assert deploy(stub, laid_out(tmp_path)) == 2
    assert "bugflow-policy-deployer" in capsys.readouterr().err


def test_a_missing_setting_is_named_before_any_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stub = StubServer()
    environ = {
        k: v for k, v in ENVIRON.items() if k != "POLICY_DEPLOY_CLIENT_SECRET"
    }
    assert deploy(stub, laid_out(tmp_path), environ=environ) == 2
    assert "POLICY_DEPLOY_CLIENT_SECRET not set" in capsys.readouterr().err
    assert stub.token_requests == []


def test_what_is_not_a_directory_is_refused_before_any_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stub = StubServer()
    assert deploy(stub, tmp_path / "absent") == 2
    assert "is not a directory" in capsys.readouterr().err
    assert stub.token_requests == []
