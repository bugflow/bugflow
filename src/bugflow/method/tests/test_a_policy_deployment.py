"""Tests of a deployment and of reading one from a directory."""

from pathlib import Path

import pytest

from bugflow.method.domain.errors import PolicyDeploymentError
from bugflow.method.domain.models.policy_deployment import (
    DeployedFile,
    PolicyDeployment,
)
from bugflow.method.infrastructure.policy_directory import PolicyDirectory
from bugflow.method.tests.policy_files import laid_out

REPOSITORY = "example-org/pull-request-policies"


def deployment(commit: str = "c1", **files: str) -> PolicyDeployment:
    texts = files or {"prose/reviewer.md": "agent_id: prose\n"}
    return PolicyDeployment(
        repository=REPOSITORY,
        commit=commit,
        files=tuple(
            DeployedFile(path=path, text=text) for path, text in texts.items()
        ),
    )


def test_the_hash_is_of_the_content_and_not_of_the_names() -> None:
    one = deployment("c1")
    other = PolicyDeployment(
        repository="another/name", commit="c9", files=one.files
    )
    assert one.content_hash == other.content_hash
    edited = deployment("c1", **{"prose/reviewer.md": "agent_id: other\n"})
    assert edited.content_hash != one.content_hash


def test_the_files_are_held_in_path_order() -> None:
    held = deployment(**{"b.md": "b", "a.md": "a"})
    assert [one.path for one in held.files] == ["a.md", "b.md"]
    assert held.text_of("b.md") == "b"
    assert held.text_of("c.md") is None


@pytest.mark.parametrize(
    "path",
    ["", "/etc/passwd", "../outside.md", "a/../b.md", "a\\b.md", "a//b"],
)
def test_a_path_outside_the_deployment_is_refused(path: str) -> None:
    with pytest.raises(PolicyDeploymentError, match="not a path inside"):
        deployment(**{path: "text"})


def test_a_path_sent_twice_is_refused() -> None:
    with pytest.raises(PolicyDeploymentError, match="more than once"):
        PolicyDeployment(
            repository=REPOSITORY,
            commit="c1",
            files=(
                DeployedFile(path="a.md", text="one"),
                DeployedFile(path="a.md", text="two"),
            ),
        )


def test_a_deployment_names_its_repository_and_its_commit() -> None:
    with pytest.raises(PolicyDeploymentError, match="names its repository"):
        PolicyDeployment(repository="", commit="c1", files=())


def test_a_directory_is_read_as_the_files_a_server_reads(
    tmp_path: Path,
) -> None:
    read = PolicyDirectory(laid_out(tmp_path)).read(REPOSITORY, "c1")
    assert (read.repository, read.commit) == (REPOSITORY, "c1")
    assert [one.path for one in read.files] == [
        "pace-layers.toml",
        "prose/doctrine/01-voice.md",
        "prose/policies/XX-01-example.md",
        "prose/reviewer.md",
    ]
