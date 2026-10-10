"""Tests of ``bugflow install-policies``: a deployment stored from a
directory on the host and put in force.

Most run the composed deploying over in-memory stores. The last runs
the command line against a real database, and is skipped unless
DATABASE_URL names a Postgres server.
"""

import io
from pathlib import Path

import pytest

from bugflow.apps.command.command import run
from bugflow.apps.shared.deploying import (
    INSTALLED_ON_THE_HOST,
    Deploying,
    deploying_with,
    run_install_policies,
)
from bugflow.method.infrastructure.in_memory_policy_deployments import (
    InMemoryPolicyDeployments,
)
from bugflow.method.infrastructure.sqlalchemy_policy_deployments import (
    SqlAlchemyPolicyDeployments,
)
from bugflow.method.tests.policy_files import laid_out
from bugflow.review.infrastructure.in_memory_review_declaration import (
    InMemoryDispatchedProcesses,
    InMemoryJudgedPolicies,
)
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal

REPOSITORY = "example-org/pull-request-policies"
DECLARATIONS = '[repository."example-org/widgets"]\npolicies = ["P-01"]\n'


class Host:
    def __init__(self) -> None:
        self.deployments = InMemoryPolicyDeployments()
        self.journal = InMemoryJournal()
        self.judged = InMemoryJudgedPolicies()
        self.dispatched = InMemoryDispatchedProcesses()
        self.deploying: Deploying = deploying_with(
            self.deployments, self.journal, self.judged, self.dispatched, ()
        )
        self.out = io.StringIO()

    def install(
        self, directory: Path, commit: str = "c1", check_only: bool = False
    ) -> int:
        return run_install_policies(
            directory,
            REPOSITORY,
            commit,
            self.deploying,
            (),
            out=self.out,
            check_only=check_only,
        )


def test_a_directory_is_stored_and_what_is_in_force_is_printed(
    tmp_path: Path,
) -> None:
    host = Host()
    assert host.install(laid_out(tmp_path)) == 0
    in_force = host.deployments.in_force()
    assert in_force is not None
    assert (in_force.repository, in_force.commit) == (REPOSITORY, "c1")
    lines = host.out.getvalue().splitlines()
    assert lines[0].startswith(f"{REPOSITORY} at c1 is in force, 4 files")
    assert lines[1:] == [
        "  pace-layers.toml",
        "  prose/doctrine/01-voice.md",
        "  prose/policies/P-01-example.md",
        "  prose/reviewer.md",
    ]
    (fact,) = host.journal.entries
    assert fact.payload["sent_by"] == INSTALLED_ON_THE_HOST


def test_installing_again_says_it_already_was(tmp_path: Path) -> None:
    host = Host()
    host.install(laid_out(tmp_path))
    assert host.install(tmp_path) == 0
    assert "; it already was" in host.out.getvalue()
    assert len(host.journal.entries) == 1


def test_a_check_stores_nothing(tmp_path: Path) -> None:
    host = Host()
    assert host.install(laid_out(tmp_path), check_only=True) == 0
    assert host.deployments.in_force() is None
    assert host.out.getvalue().startswith("checked 4 files")
    assert "nothing stored" in host.out.getvalue()


def test_files_that_do_not_parse_exit_1_with_the_reasons(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    host = Host()
    laid_out(tmp_path)
    (tmp_path / "prose/policies/P-01-example.md").write_text("broken\n")
    assert host.install(tmp_path) == 1
    assert "P-01-example.md" in capsys.readouterr().err
    assert host.deployments.in_force() is None


def test_a_commit_held_with_other_content_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    host = Host()
    host.install(laid_out(tmp_path))
    (tmp_path / "prose/doctrine/01-voice.md").write_text("Changed.\n")
    assert host.install(tmp_path) == 1
    assert "already held with other content" in capsys.readouterr().err


def test_the_declarations_are_written_and_said(tmp_path: Path) -> None:
    host = Host()
    laid_out(tmp_path)
    (tmp_path / "declarations.toml").write_text(DECLARATIONS)
    assert host.install(tmp_path) == 0
    assert host.judged.judged("github", "example-org/widgets") == {"P-01"}
    assert "1 repositories are declared by declarations.toml" in (
        host.out.getvalue()
    )


def test_what_is_not_a_directory_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    host = Host()
    assert host.install(tmp_path / "absent") == 2
    assert "is not a directory" in capsys.readouterr().err


def test_the_command_needs_the_database_url(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = run(
        [
            "install-policies",
            str(laid_out(tmp_path)),
            "--repository",
            REPOSITORY,
            "--commit",
            "c1",
        ],
        environ={},
    )
    assert status == 2
    assert "DATABASE_URL not set" in capsys.readouterr().err


def test_the_command_line_stores_the_deployment_in_the_database(
    tmp_path: Path, database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    status = run(
        [
            "install-policies",
            str(laid_out(tmp_path)),
            "--repository",
            REPOSITORY,
            "--commit",
            "c1",
        ],
        environ={"DATABASE_URL": database_url, "BUILD_SHA": "3" * 40},
    )
    assert status == 0
    assert capsys.readouterr().out.startswith(
        f"{REPOSITORY} at c1 is in force"
    )
    in_force = SqlAlchemyPolicyDeployments(database_url).in_force()
    assert in_force is not None
    assert len(in_force.files) == 4
