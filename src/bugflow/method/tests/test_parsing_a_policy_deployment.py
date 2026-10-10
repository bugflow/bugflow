"""Tests of parsing the files of a deployment, and of refusing one that
does not parse."""

import pytest

from bugflow.method.domain.errors import PolicyDeploymentError
from bugflow.method.domain.models.policy_deployment import (
    DeployedFile,
    PolicyDeployment,
)
from bugflow.method.infrastructure.policy_deployment_parsing import (
    parse_deployment,
)
from bugflow.method.tests.policy_files import (
    DOCTRINE,
    MANIFEST,
    POLICY,
    READ,
    TOPOLOGY,
)

REPOSITORY = "example-org/pull-request-policies"


def deployment(files: dict[str, str]) -> PolicyDeployment:
    return PolicyDeployment(
        repository=REPOSITORY,
        commit="c1",
        files=tuple(
            DeployedFile(path=path, text=text) for path, text in files.items()
        ),
    )


def test_a_valid_deployment_parses_into_its_four_parts() -> None:
    parsed = parse_deployment(deployment(READ))
    assert list(parsed.agents) == ["prose"]
    assert parsed.agents["prose"].runner == "judge"
    assert list(parsed.policies["prose"]) == ["P-01"]
    assert parsed.policies["prose"]["P-01"].evidence == "description"
    assert parsed.doctrine["prose"].text == DOCTRINE
    assert list(parsed.layers) == ["pull-request"]


def test_a_deployment_with_no_files_parses_to_nothing() -> None:
    parsed = parse_deployment(deployment({}))
    assert parsed.agents == {}
    assert parsed.policies == {}
    assert parsed.layers == {}
    assert parsed.declared is None


def test_doctrine_files_are_joined_in_filename_order() -> None:
    files = READ | {"prose/doctrine/00-first.md": "**EX-0.** First.\n"}
    parsed = parse_deployment(deployment(files))
    assert parsed.doctrine["prose"].text == "**EX-0.** First.\n" + DOCTRINE


def test_an_agent_with_no_policy_files_has_no_policies() -> None:
    parsed = parse_deployment(deployment({"prose/reviewer.md": MANIFEST}))
    assert parsed.policies == {"prose": {}}
    assert "prose" not in parsed.doctrine


def test_the_prose_of_an_agent_is_its_files_down_to_calibration() -> None:
    parsed = parse_deployment(deployment(READ))
    asked = POLICY.partition("\n=== calibration\n")[0]
    assert parsed.policy_sources["prose"] == asked
    assert parsed.prose["prose"] == MANIFEST + asked + DOCTRINE


def test_a_check_the_server_names_is_accepted_and_another_refused() -> None:
    manifest = MANIFEST.replace(
        "policies: P-01\n", "policies: P-01, P-02\nchecks: em-dash P-02 EX-2\n"
    )
    files = READ | {"prose/reviewer.md": manifest}
    parsed = parse_deployment(deployment(files), checks=("em-dash",))
    assert parsed.agents["prose"].checks[0].policy_id == "P-02"
    with pytest.raises(PolicyDeploymentError, match="not a check"):
        parse_deployment(deployment(files), checks=("spelling",))


@pytest.mark.parametrize(
    ("files", "problem"),
    [
        ({"notes.txt": "x"}, "notes.txt: not a file a server reads"),
        (
            {"prose/cases/one.json": "{}"},
            "prose/cases/one.json: not a file a server reads",
        ),
        (
            {"prose/reviewer.md": "agent_id: prose\n"},
            "prose/reviewer.md: no ---",
        ),
        (
            {"prose/reviewer.md": MANIFEST, "again/reviewer.md": MANIFEST},
            "a second agent with the id prose",
        ),
        (
            {"prose/policies/P-01-example.md": POLICY},
            "prose/policies/P-01-example.md: prose/reviewer.md is missing",
        ),
        (
            {"prose/doctrine/01-voice.md": DOCTRINE},
            "prose/doctrine/01-voice.md: prose/reviewer.md is missing",
        ),
        (
            {
                "prose/reviewer.md": MANIFEST,
                "prose/policies/P-01-example.md": "policy_id: P-01\n",
            },
            "prose/policies/P-01-example.md: no --- line",
        ),
        (
            {
                "prose/reviewer.md": MANIFEST,
                "prose/policies/P-01-example.md": POLICY,
                "prose/policies/P-01-again.md": POLICY,
            },
            "a second policy with the id P-01",
        ),
        (
            {
                "prose/reviewer.md": MANIFEST,
                "prose/policies/P-01-example.md": POLICY.replace(
                    "evidence: description", "evidence: telepathy"
                ),
            },
            "evidence 'telepathy' is not one of",
        ),
        (
            {"pace-layers.toml": TOPOLOGY.replace('"event"', '"hourly"')},
            "pace-layers.toml:",
        ),
    ],
)
def test_a_deployment_that_does_not_parse_is_refused(
    files: dict[str, str], problem: str
) -> None:
    with pytest.raises(PolicyDeploymentError) as refused:
        parse_deployment(deployment(files))
    assert problem in str(refused.value)


def test_every_problem_is_reported_at_once() -> None:
    files = {
        "notes.txt": "x",
        "prose/reviewer.md": "agent_id: prose\n",
        "pace-layers.toml": "not toml [",
    }
    with pytest.raises(PolicyDeploymentError) as refused:
        parse_deployment(deployment(files))
    said = str(refused.value)
    assert "notes.txt" in said
    assert "prose/reviewer.md" in said
    assert "pace-layers.toml" in said
