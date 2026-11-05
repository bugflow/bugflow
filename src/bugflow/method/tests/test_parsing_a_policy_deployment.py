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
    EDITED,
    EDITOR,
    GOOD_EXAMPLE,
    MANIFEST,
    POLICY,
    READ,
    REFERENCES,
    SKILL,
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


@pytest.mark.model(
    "Gnome",
    "A gnome's doctrine/ holds its clauses.",
)
@pytest.mark.model(
    "Gnome",
    "A gnome's policies/ holds its policies.",
)
@pytest.mark.model(
    "Parsing",
    "The policy package parser reads each reviewer's manifest, doctrine "
    "and policies, and the binding's two files.",
)
@pytest.mark.model(
    "Reviewer",
    "A server has a reviewer for each gnome, named by the gnome's id.",
)
def test_a_valid_deployment_parses_into_its_four_parts() -> None:
    parsed = parse_deployment(deployment(READ))
    assert list(parsed.agents) == ["prose"]
    assert parsed.agents["prose"].runner == "judge"
    assert list(parsed.policies["prose"]) == ["P-01"]
    assert parsed.policies["prose"]["P-01"].evidence == (
        "pull-request/description"
    )
    assert parsed.doctrine["prose"].text == DOCTRINE
    assert list(parsed.layers) == ["pull-request"]


def test_a_manifest_named_manifest_is_read_as_one_named_reviewer() -> None:
    files = {
        path.replace("reviewer.md", "manifest.md"): text
        for path, text in READ.items()
    }
    parsed = parse_deployment(deployment(files))
    assert list(parsed.agents) == ["prose"]
    assert list(parsed.policies["prose"]) == ["P-01"]


@pytest.mark.model(
    "Skill",
    "A reviewer with no originals and one skill is read from that skill's"
    " references/.",
)
def test_a_reviewer_with_the_files_in_its_one_skill_is_read_from_it() -> None:
    files = {
        path.replace(f"{REFERENCES}/policies", f"{SKILL}/policies").replace(
            f"{REFERENCES}/doctrine", f"{SKILL}/doctrine"
        ): text
        for path, text in READ.items()
    }
    parsed = parse_deployment(deployment(files))
    assert list(parsed.policies["prose"]) == ["P-01"]
    assert parsed.doctrine["prose"].text == DOCTRINE
    assert parsed.prose == parse_deployment(deployment(READ)).prose


@pytest.mark.model(
    "Skill",
    "The server reads a reviewer's originals and passes over a skill's "
    "copies.",
)
def test_a_skills_copy_of_the_files_is_not_read() -> None:
    stale = "**EX-9.** A stale copy.\n"
    files = READ | {f"{SKILL}/doctrine/01-voice.md": stale}
    parsed = parse_deployment(deployment(files))
    assert parsed.doctrine["prose"].text == DOCTRINE
    assert parsed.prose == parse_deployment(deployment(READ)).prose


def test_a_deployment_with_no_files_parses_to_nothing() -> None:
    parsed = parse_deployment(deployment({}))
    assert parsed.agents == {}
    assert parsed.policies == {}
    assert parsed.layers == {}
    assert parsed.profiles == {}


@pytest.mark.model(
    "Gnome",
    "A gnome's doctrine/ holds its clauses.",
)
def test_doctrine_files_are_joined_in_filename_order() -> None:
    files = READ | {f"{REFERENCES}/doctrine/00-first.md": "**EX-0.** First.\n"}
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


@pytest.mark.model(
    "Parsing",
    "The parser refuses a file that a server does not read, such as a case.",
)
@pytest.mark.model(
    "Skill",
    "The server never runs a skill's scripts/check-*.",
)
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
            {"prose/reviewer.md": MANIFEST, "prose/manifest.md": MANIFEST},
            "prose/reviewer.md: a second manifest in prose/",
        ),
        (
            {f"{REFERENCES}/policies/P-01-example.md": POLICY},
            f"{REFERENCES}/policies/P-01-example.md: "
            "prose/reviewer.md is missing",
        ),
        (
            {f"{REFERENCES}/doctrine/01-voice.md": DOCTRINE},
            f"{REFERENCES}/doctrine/01-voice.md: prose/reviewer.md is missing",
        ),
        (
            {
                "prose/reviewer.md": MANIFEST,
                f"{REFERENCES}/policies/P-01-example.md": "policy_id: P-01\n",
            },
            f"{REFERENCES}/policies/P-01-example.md: no --- line",
        ),
        (
            {
                "prose/reviewer.md": MANIFEST,
                f"{REFERENCES}/policies/P-01-example.md": POLICY,
                f"{REFERENCES}/policies/P-01-again.md": POLICY,
            },
            "a second policy with the id P-01",
        ),
        (
            {
                "prose/reviewer.md": MANIFEST,
                f"{REFERENCES}/policies/P-01-example.md": POLICY.replace(
                    "evidence: description", "evidence: telepathy"
                ),
            },
            "evidence 'telepathy' is not a subject",
        ),
        (
            {"pace-layers.toml": TOPOLOGY.replace('"event"', '"hourly"')},
            "pace-layers.toml:",
        ),
        (
            {
                "prose/reviewer.md": MANIFEST,
                f"{SKILL}/doctrine/01-voice.md": DOCTRINE,
                "prose/skills/other/references/doctrine/01-voice.md": DOCTRINE,
            },
            "prose/: the policies and the doctrine are in "
            "prose/skills/other/references/ and "
            "prose/skills/prose-write/references/, and prose/ has no "
            "policies/ or doctrine/ of its own",
        ),
        (
            {
                "prose/reviewer.md": MANIFEST,
                "prose/skills/prose-write/scripts/check-example.md": "x",
            },
            "prose/skills/prose-write/scripts/check-example.md: "
            "not a file a server reads",
        ),
    ],
)
def test_a_deployment_that_does_not_parse_is_refused(
    files: dict[str, str], problem: str
) -> None:
    with pytest.raises(PolicyDeploymentError) as refused:
        parse_deployment(deployment(files))
    assert problem in str(refused.value)


@pytest.mark.model(
    "Parsing",
    "The parser reports the problem in each file that has one.",
)
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


@pytest.mark.model(
    "Glossary",
    "A deployment may hold the words documents under glossary/.",
)
def test_the_glossary_files_are_kept_in_path_order() -> None:
    files = READ | {
        "glossary/clankos/docs/words.txt": "garden: a tree\n",
        "glossary/bugflow/docs/words.md": "- **Poller.** A loop.\n",
        "glossary/notes.org": "* Words\n",
    }
    parsed = parse_deployment(deployment(files))
    assert parsed.glossary == {
        "glossary/bugflow/docs/words.md": "- **Poller.** A loop.\n",
        "glossary/clankos/docs/words.txt": "garden: a tree\n",
        "glossary/notes.org": "* Words\n",
    }
    assert list(parsed.glossary) == sorted(parsed.glossary)
    assert list(parsed.agents) == ["prose"]


def test_a_deployment_with_no_glossary_has_an_empty_one() -> None:
    assert parse_deployment(deployment(READ)).glossary == {}


def test_a_glossary_file_of_another_name_is_refused() -> None:
    files = READ | {"glossary/clankos/words.json": "{}\n"}
    with pytest.raises(
        PolicyDeploymentError,
        match=r"glossary/clankos/words\.json: a glossary file ends in",
    ):
        parse_deployment(deployment(files))


def test_a_glossary_file_is_not_read_as_a_reviewers_file() -> None:
    """A path under glossary/ is a glossary file whatever its
    directories are called."""
    files = READ | {"glossary/policies/P-09-example.md": "words\n"}
    parsed = parse_deployment(deployment(files))
    assert list(parsed.agents) == ["prose"]
    assert list(parsed.glossary) == ["glossary/policies/P-09-example.md"]


@pytest.mark.model(
    "Editor",
    "A binding may carry an editor: editor.md, and its examples under "
    "editor/examples/.",
)
def test_the_editor_is_read_with_its_examples_in_path_order() -> None:
    parsed = parse_deployment(deployment(READ | EDITED))
    editor = parsed.editor
    assert editor is not None
    assert editor.model_class == "medium"
    assert editor.instructions.startswith("You edit the draft")
    assert [one.name for one in editor.examples] == [
        "bad-01-every-finding",
        "good-01-one-fix",
    ]
    assert [one.kind for one in editor.examples] == ["bad", "good"]
    assert [one.name for one in editor.of_kind("good")] == ["good-01-one-fix"]
    assert editor.examples[1].why == (
        "One thing to fix, named first, with what to do about it."
    )
    assert editor.examples[1].text.startswith("The commit changes two")
    assert list(parsed.agents) == ["prose"]


def test_a_binding_without_an_editor_has_none() -> None:
    assert parse_deployment(deployment(READ)).editor is None


def test_an_editor_with_no_examples_is_read() -> None:
    parsed = parse_deployment(deployment(READ | {"editor.md": EDITOR}))
    assert parsed.editor is not None
    assert parsed.editor.examples == ()


@pytest.mark.model(
    "Editor",
    "Examples with no editor.md are refused.",
)
def test_examples_with_no_editor_are_refused() -> None:
    files = READ | {"editor/examples/good-01-one-fix.md": GOOD_EXAMPLE}
    with pytest.raises(
        PolicyDeploymentError, match=r"editor/examples/: editor\.md is missing"
    ):
        parse_deployment(deployment(files))


@pytest.mark.model(
    "Editor",
    "An example is named good-NN-name.md or bad-NN-name.md and says why.",
)
def test_an_example_of_another_name_is_refused() -> None:
    files = READ | EDITED | {"editor/examples/fine-01-x.md": GOOD_EXAMPLE}
    with pytest.raises(
        PolicyDeploymentError,
        match=r"editor/examples/fine-01-x\.md: an example is named",
    ):
        parse_deployment(deployment(files))


def test_an_example_without_a_why_is_refused() -> None:
    files = (
        READ
        | EDITED
        | {"editor/examples/good-02-no-why.md": "---\nA comment.\n"}
    )
    with pytest.raises(
        PolicyDeploymentError, match=r"good-02-no-why\.md: no why line"
    ):
        parse_deployment(deployment(files))


def test_an_editor_of_an_unknown_model_class_is_refused() -> None:
    files = READ | {"editor.md": "model_class: huge\n---\nEdit.\n"}
    with pytest.raises(
        PolicyDeploymentError, match=r"model class is one of small, medium"
    ):
        parse_deployment(deployment(files))


def test_a_file_under_the_editors_directory_is_not_a_reviewers() -> None:
    """editor/ is the editor's, so a manifest there is refused rather
    than read as a reviewer named editor."""
    files = READ | EDITED | {"editor/manifest.md": MANIFEST}
    with pytest.raises(
        PolicyDeploymentError,
        match=r"editor/manifest\.md: not a file a server reads",
    ):
        parse_deployment(deployment(files))


def test_every_editor_problem_is_reported_at_once() -> None:
    files = READ | {
        "editor.md": "model_class: huge\n---\nEdit.\n",
        "editor/examples/good-01-one-fix.md": "no header\n",
    }
    with pytest.raises(PolicyDeploymentError) as refused:
        parse_deployment(deployment(files))
    assert "model class is one of" in str(refused.value)
    assert "good-01-one-fix.md: no --- line" in str(refused.value)
