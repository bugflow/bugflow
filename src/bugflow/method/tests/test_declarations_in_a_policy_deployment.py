"""Tests of the declarations file a deployment may carry, which says
what each repository is judged on and what it dispatches. It is parsed
to plain data; writing the declarations is the application's."""

import pytest

from bugflow.method.domain.errors import PolicyDeploymentError
from bugflow.method.domain.models.policy_deployment import (
    DeployedFile,
    PolicyDeployment,
)
from bugflow.method.infrastructure.policy_deployment_parsing import (
    RepositoryDeclaration,
    parse_deployment,
)
from bugflow.method.tests.policy_files import MANIFEST, READ

REPOSITORY = "example-org/pull-request-policies"

#: A reviewer with one judged policy and one a check answers.
CHECKING = MANIFEST.replace(
    "policies: P-01\n", "policies: P-01, P-02\nchecks: em-dash P-02 EX-2\n"
)

DECLARATIONS = """\
[repository."example-org/widgets"]
policies = ["P-01", "P-02"]
processes = ["evaluate-pull-request"]

[repository."forgejo:example-org/gears"]
policies = ["P-01"]
"""


def deployment(declarations: str | None = DECLARATIONS) -> PolicyDeployment:
    files = READ | {"prose/reviewer.md": CHECKING}
    if declarations is not None:
        files["declarations.toml"] = declarations
    return PolicyDeployment(
        repository=REPOSITORY,
        commit="c1",
        files=tuple(
            DeployedFile(path=path, text=text) for path, text in files.items()
        ),
    )


def test_a_deployment_without_the_file_declares_nothing() -> None:
    assert parse_deployment(deployment(None)).declared is None


def test_the_file_is_parsed_into_a_declaration_for_each_repository() -> None:
    assert parse_deployment(deployment()).declared == (
        RepositoryDeclaration(
            forge="github",
            repo="example-org/widgets",
            policies=("P-01", "P-02"),
            processes=("evaluate-pull-request",),
        ),
        RepositoryDeclaration(
            forge="forgejo",
            repo="example-org/gears",
            policies=("P-01",),
            processes=(),
        ),
    )


def test_a_file_that_declares_no_repository_is_an_empty_declaration() -> None:
    assert parse_deployment(deployment("")).declared == ()


def test_a_policy_a_check_answers_is_known_from_the_manifest() -> None:
    """P-02 has no file. The manifest's checks line names it, and that
    is what makes it a policy this deployment holds."""
    files = dict(READ)
    files["declarations.toml"] = DECLARATIONS
    held = PolicyDeployment(
        repository=REPOSITORY,
        commit="c1",
        files=tuple(
            DeployedFile(path=path, text=text) for path, text in files.items()
        ),
    )
    with pytest.raises(PolicyDeploymentError, match="P-02 is not a policy"):
        parse_deployment(held)


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("not toml [", "declarations.toml:"),
        ("[settings]\nx = 1\n", "settings is not a table this file has"),
        (
            '[repository."widgets"]\n',
            "repository 'widgets' is not owner/name or forge:owner/name",
        ),
        (
            '[repository."o/r"]\npolicies = ["P-99"]\n',
            "P-99 is not a policy this deployment holds",
        ),
        (
            '[repository."o/r"]\nprocesses = ["nightly-sweep"]\n',
            "nightly-sweep is not a process this deployment holds",
        ),
        (
            '[repository."o/r"]\npolicies = "P-01"\n',
            "policies must be a list of names",
        ),
        (
            '[repository."o/r"]\nbudget = 5\n',
            "budget is not policies or processes",
        ),
    ],
)
def test_a_file_that_is_wrong_is_refused(text: str, problem: str) -> None:
    with pytest.raises(PolicyDeploymentError) as refused:
        parse_deployment(deployment(text))
    assert problem in str(refused.value)
