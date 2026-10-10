"""Tests of reading reviewers from their directories."""

from pathlib import Path

import pytest

from bugflow.method.domain.errors import ReviewAgentError
from bugflow.method.infrastructure.reviewer_packages import (
    CheckedPolicy,
    DomainSpecificReviewAgent,
    installed,
    load_agents,
    parse_agent,
)

MANIFEST = """\
agent_id: safety
summary: Whether a change can be misused
runner: checkout
governs: yes
policies: S-01, S-02
---
What it reads and what it refuses to read.
"""


def write(directory: Path, name: str, text: str = MANIFEST) -> Path:
    agent = directory / name
    agent.mkdir()
    (agent / "reviewer.md").write_text(text)
    return agent


def test_a_manifest_gives_the_reviewers_fields_and_its_prose() -> None:
    agent = parse_agent(Path("safety/reviewer.md"), MANIFEST)

    assert agent.agent_id == "safety"
    assert agent.summary == "Whether a change can be misused"
    assert (agent.runner, agent.governs) == ("checkout", True)
    assert agent.policies == ("S-01", "S-02")
    assert agent.checks == ()
    assert agent.description == "What it reads and what it refuses to read."


def test_a_reviewer_with_no_policies_has_none() -> None:
    text = MANIFEST.replace("policies: S-01, S-02\n", "")

    assert parse_agent(Path("a/reviewer.md"), text).policies == ()


def test_a_manifest_missing_a_required_field_is_refused() -> None:
    text = MANIFEST.replace("runner: checkout\n", "")

    with pytest.raises(ValueError, match="missing runner"):
        parse_agent(Path("a/reviewer.md"), text)


def test_a_manifest_with_no_line_of_dashes_is_refused() -> None:
    with pytest.raises(ValueError, match="no --- line"):
        parse_agent(Path("a/reviewer.md"), "agent_id: a\n")


def test_a_header_line_that_is_not_key_and_value_is_refused() -> None:
    text = MANIFEST.replace("runner: checkout", "runner checkout")

    with pytest.raises(ValueError, match="is not key: value"):
        parse_agent(Path("a/reviewer.md"), text)


def test_governs_must_be_yes_or_no() -> None:
    text = MANIFEST.replace("governs: yes", "governs: sometimes")

    with pytest.raises(ValueError, match="not yes or no"):
        parse_agent(Path("a/reviewer.md"), text)


def with_checks(checks: str) -> str:
    return MANIFEST.replace("---\n", f"checks: {checks}\n---\n", 1)


def test_a_reviewer_says_which_policy_a_check_answers() -> None:
    agent = parse_agent(
        Path("a/reviewer.md"), with_checks("em-dash S-02 RULE-21")
    )

    assert agent.checks == (
        CheckedPolicy(check="em-dash", policy_id="S-02", clause="RULE-21"),
    )


def test_a_check_this_server_does_not_have_is_refused() -> None:
    with pytest.raises(ValueError, match="'spelling' is not a check"):
        parse_agent(
            Path("a/reviewer.md"),
            with_checks("spelling S-02 R-1"),
            checks=("em-dash",),
        )


def test_a_caller_that_names_no_check_leaves_the_name_unchecked() -> None:
    agent = parse_agent(
        Path("a/reviewer.md"), with_checks("spelling S-02 R-1")
    )

    assert agent.checks[0].check == "spelling"


def test_a_check_for_a_policy_the_reviewer_does_not_have_is_refused() -> None:
    with pytest.raises(ValueError, match="answers S-09"):
        parse_agent(Path("a/reviewer.md"), with_checks("em-dash S-09 R-1"))


def test_a_check_that_is_not_three_words_is_refused() -> None:
    with pytest.raises(ValueError, match="is not a check's name"):
        parse_agent(Path("a/reviewer.md"), with_checks("em-dash S-02"))


def test_a_reviewers_policies_and_doctrine_are_beside_its_manifest(
    tmp_path: Path,
) -> None:
    write(tmp_path, "safety")

    agent = load_agents(tmp_path)["safety"]

    assert agent.policy_dir == tmp_path / "safety/policies"
    assert agent.doctrine_dir == tmp_path / "safety/doctrine"


def test_a_directory_with_no_manifest_is_not_a_reviewer(
    tmp_path: Path,
) -> None:
    write(tmp_path, "safety")
    (tmp_path / "notes").mkdir()

    assert list(load_agents(tmp_path)) == ["safety"]


def test_an_empty_or_missing_directory_holds_no_reviewer(
    tmp_path: Path,
) -> None:
    assert load_agents(tmp_path) == {}
    assert load_agents(tmp_path / "absent") == {}


def test_two_reviewers_with_one_agent_id_are_refused(tmp_path: Path) -> None:
    write(tmp_path, "safety")
    write(tmp_path, "safety-again")

    with pytest.raises(ReviewAgentError, match="claim safety"):
        load_agents(tmp_path)


def agents(*ids: str) -> dict[str, DomainSpecificReviewAgent]:
    return {
        agent_id: parse_agent(
            Path(f"{agent_id}/reviewer.md"),
            MANIFEST.replace("agent_id: safety", f"agent_id: {agent_id}"),
        )
        for agent_id in ids
    }


def test_naming_no_reviewer_gives_all_of_them() -> None:
    assert list(installed([], agents("prose", "safety"))) == [
        "prose",
        "safety",
    ]
    assert installed((), {}) == {}


def test_naming_reviewers_gives_only_those() -> None:
    assert list(installed(["prose"], agents("prose", "safety"))) == ["prose"]


def test_naming_a_reviewer_that_is_not_installed_is_refused() -> None:
    with pytest.raises(ReviewAgentError, match="not installed: design"):
        installed(["design"], agents("prose"))
