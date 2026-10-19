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
from bugflow.method.tests.policy_files import (
    MANIFEST,
    POLICY,
    READ,
    REFERENCES,
)

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


#: A policy a check answers, with no check on the manifest, and one
#: reading a scope, which a pull request judge does not render.
CHECKED = POLICY.replace("policy_id: P-01", "policy_id: P-03").replace(
    "model_class: small", "model_class: none\nimplemented: check"
)
SCOPED = POLICY.replace("policy_id: P-01", "policy_id: P-04").replace(
    "evidence: description", "evidence: scope/canon"
)


def deployment(
    declarations: str | None = DECLARATIONS,
    more: dict[str, str] | None = None,
) -> PolicyDeployment:
    files = READ | {"prose/reviewer.md": CHECKING} | (more or {})
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


@pytest.mark.model(
    "Binding",
    "A binding's declarations.toml pairs policies with repositories.",
)
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


HOLDING_BOTH = {
    "prose/reviewer.md": CHECKING.replace(
        "policies: P-01, P-02", "policies: P-01, P-02, P-03, P-04"
    ),
    f"{REFERENCES}/policies/P-03-checked.md": CHECKED,
    f"{REFERENCES}/policies/P-04-scoped.md": SCOPED,
}


def test_a_policy_this_server_cannot_answer_may_be_held_and_not_declared() -> (
    None
):
    """A gnome may hold a policy for another consumer: a check a
    garden's lint runs, or a subject a pull request judge does not
    render. The server parses it, and judges by the rest."""
    parsed = parse_deployment(
        deployment(more=HOLDING_BOTH),
        checks=("em-dash",),
        subjects=("pull-request/description",),
    )
    assert sorted(parsed.policies["prose"]) == ["P-01", "P-03", "P-04"]


@pytest.mark.model(
    "Reviewer",
    "A deployment that declares a policy this server cannot answer is "
    "refused.",
)
@pytest.mark.parametrize(
    ("policy_id", "problem"),
    [
        ("P-03", "P-03 is answered by a check, and no manifest gives it one"),
        ("P-04", "P-04 reads scope/canon, which this server does not render"),
    ],
)
def test_declaring_a_policy_this_server_cannot_answer_is_refused(
    policy_id: str, problem: str
) -> None:
    declarations = DECLARATIONS.replace(
        'policies = ["P-01", "P-02"]', f'policies = ["P-01", "{policy_id}"]'
    )
    with pytest.raises(PolicyDeploymentError, match=problem):
        parse_deployment(
            deployment(declarations, HOLDING_BOTH),
            checks=("em-dash",),
            subjects=("pull-request/description",),
        )


def test_a_server_that_does_not_know_its_subjects_refuses_no_subject() -> None:
    declarations = DECLARATIONS.replace(
        'policies = ["P-01", "P-02"]', 'policies = ["P-01", "P-04"]'
    )
    parsed = parse_deployment(deployment(declarations, HOLDING_BOTH))
    assert parsed.declared is not None
    assert parsed.declared[0].policies == ("P-01", "P-04")
