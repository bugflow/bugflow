"""Tests of the profiles file a deployment may carry, which names sets
of each reviewer's policies. A repository's setting for a reviewer
names one of them; every reviewer has ``default``."""

import pytest

from bugflow.method.domain.errors import PolicyDeploymentError
from bugflow.method.domain.models.policy_deployment import (
    DeployedFile,
    PolicyDeployment,
)
from bugflow.method.domain.models.policy_text import JUDGED_SUBJECTS
from bugflow.method.infrastructure.policy_deployment_parsing import (
    ParsedDeployment,
    ParsedPolicyDeploymentCheck,
    parse_deployment,
)
from bugflow.method.tests.policy_files import (
    MANIFEST,
    POLICY,
    READ,
    REFERENCES,
)

#: A reviewer with two judged policies, one a check answers, and one
#: reading a scope, which a pull request judge does not render.
HOLDING = {
    "prose/reviewer.md": MANIFEST.replace(
        "policies: P-01\n",
        "policies: P-01, P-02, P-03, P-04\nchecks: em-dash P-03 EX-2\n",
    ),
    f"{REFERENCES}/policies/P-02-other.md": POLICY.replace(
        "policy_id: P-01", "policy_id: P-02"
    ),
    f"{REFERENCES}/policies/P-04-scoped.md": POLICY.replace(
        "policy_id: P-01", "policy_id: P-04"
    ).replace("evidence: description", "evidence: scope/canon"),
}

PROFILES = """\
[profile.prose.default]
policies = ["P-01", "P-03"]

[profile.prose.strict]
policies = ["P-01", "P-02", "P-03"]
"""


def deployment(profiles: str | None = PROFILES) -> PolicyDeployment:
    files = READ | HOLDING
    if profiles is not None:
        files["profiles.toml"] = profiles
    return PolicyDeployment(
        repository="example-org/pull-request-policies",
        commit="c1",
        files=tuple(
            DeployedFile(path=path, text=text) for path, text in files.items()
        ),
    )


def parsed(profiles: str | None = PROFILES) -> ParsedDeployment:
    return parse_deployment(
        deployment(profiles),
        checks=("em-dash",),
        subjects=("pull-request/description",),
    )


@pytest.mark.model(
    "Binding",
    "A reviewer the binding names no default profile for has one of every "
    "policy of it the server answers.",
)
def test_without_the_file_each_reviewer_has_a_default_of_all_it_answers() -> (
    None
):
    """P-04 reads a scope this server does not render, so the default
    leaves it out rather than refuse the deployment."""
    assert parsed(None).profiles == {
        "prose": {"default": ("P-01", "P-02", "P-03")}
    }


@pytest.mark.model(
    "Binding",
    "A binding's profiles.toml names sets of a reviewer's policies.",
)
def test_the_file_names_each_reviewers_profiles() -> None:
    assert parsed().profiles == {
        "prose": {
            "default": ("P-01", "P-03"),
            "strict": ("P-01", "P-02", "P-03"),
        }
    }


def test_a_reviewer_the_file_gives_no_default_still_has_one() -> None:
    only_strict = '[profile.prose.strict]\npolicies = ["P-01"]\n'
    assert parsed(only_strict).profiles == {
        "prose": {"default": ("P-01", "P-02", "P-03"), "strict": ("P-01",)}
    }


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("not toml [", "profiles.toml:"),
        ("[settings]\nx = 1\n", "settings is not a table this file has"),
        (
            '[profile.other.default]\npolicies = ["P-01"]\n',
            "other is not a reviewer this deployment holds",
        ),
        (
            '[profile.prose.Strict]\npolicies = ["P-01"]\n',
            "a profile's name is lower case letters, digits and hyphens",
        ),
        (
            '[profile.prose.default]\npolicies = ["P-99"]\n',
            "P-99 is not a policy of prose",
        ),
        (
            '[profile.prose.default]\npolicies = "P-01"\n',
            "policies must be a list of names",
        ),
        (
            '[profile.prose.default]\nbehaviour = "gate"\n',
            "behaviour is not policies",
        ),
    ],
)
def test_a_file_that_is_wrong_is_refused(text: str, problem: str) -> None:
    with pytest.raises(PolicyDeploymentError) as refused:
        parsed(text)
    assert problem in str(refused.value)


@pytest.mark.model(
    "Reviewer",
    "A profile of a policy this server cannot answer is refused.",
)
def test_a_profile_of_a_policy_this_server_cannot_answer_is_refused() -> None:
    with pytest.raises(
        PolicyDeploymentError,
        match="P-04 reads scope/canon, which this server does not render",
    ):
        parsed('[profile.prose.default]\npolicies = ["P-04"]\n')


def with_declarations() -> PolicyDeployment:
    files = READ | {"declarations.toml": '[repository."o/r"]\n'}
    return PolicyDeployment(
        repository="example-org/pull-request-policies",
        commit="c1",
        files=tuple(
            DeployedFile(path=path, text=text) for path, text in files.items()
        ),
    )


@pytest.mark.model("Binding", "A binding's declarations.toml is refused.")
def test_a_declarations_file_is_refused() -> None:
    with pytest.raises(PolicyDeploymentError, match="retired by ADR 008"):
        ParsedPolicyDeploymentCheck().check(with_declarations())


@pytest.mark.model(
    "Binding",
    "A deployment in force that carries declarations.toml is read without it.",
)
def test_a_deployment_in_force_with_declarations_is_read_without_them() -> (
    None
):
    assert parse_deployment(with_declarations()).agents


@pytest.mark.model(
    "Glossary",
    "A profile of a policy whose subject is document/glossary is accepted.",
)
def test_a_profile_of_a_policy_that_reads_the_glossary_is_accepted() -> None:
    glossed = POLICY.replace("policy_id: P-01", "policy_id: P-05").replace(
        "evidence: description", "evidence: document/glossary"
    )
    files = READ | {
        "prose/reviewer.md": MANIFEST.replace(
            "policies: P-01\n", "policies: P-01, P-05\n"
        ),
        f"{REFERENCES}/policies/P-05-glossary.md": glossed,
        "glossary/clankos/docs/words.txt": "garden: a tree\n",
        "profiles.toml": (
            '[profile.prose.default]\npolicies = ["P-01", "P-05"]\n'
        ),
    }
    held = parse_deployment(
        PolicyDeployment(
            repository="example-org/pull-request-policies",
            commit="c1",
            files=tuple(
                DeployedFile(path=path, text=text)
                for path, text in files.items()
            ),
        ),
        subjects=JUDGED_SUBJECTS,
    )
    assert held.profiles["prose"]["default"] == ("P-01", "P-05")
