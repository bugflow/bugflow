"""The model section of docs/architecture.md, written from
docs/model.toml and the tests marked with pytest.mark.model.

Run as ``python -m bugflow.shared.tests.model_section`` to write the
section; test_the_model_section_is_written_from_the_tests checks that
it is current.
"""

import ast
import textwrap
import tomllib
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[4]
REQUIREMENTS = REPOSITORY / "docs" / "model.toml"
ARCHITECTURE = REPOSITORY / "docs" / "architecture.md"
BEGIN = "<!-- Written from docs/model.toml: python -m "
BEGIN += "bugflow.shared.tests.model_section -->\n"
END = "<!-- End of the section written from docs/model.toml -->\n"


def requirements() -> list[dict[str, str]]:
    """Each requirement of docs/model.toml, in order."""
    with REQUIREMENTS.open("rb") as file:
        found: list[dict[str, str]] = tomllib.load(file)["requirement"]
    return found


def things() -> list[str]:
    """The things the model names, in order."""
    with REQUIREMENTS.open("rb") as file:
        found: list[str] = tomllib.load(file)["things"]
    return found


def marks() -> list[tuple[str, str, Path]]:
    """The group and requirement of each pytest.mark.model in the tests,
    with the file that holds it, read without running the tests."""
    found = []
    for directory in ("src", "deployments"):
        for path in sorted((REPOSITORY / directory).rglob("test_*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if (
                    isinstance(node, ast.Call)
                    and ast.unparse(node.func) == "pytest.mark.model"
                ):
                    group, text = (ast.literal_eval(a) for a in node.args)
                    found.append((group, text, path))
    return found


def section() -> str:
    """The section's Markdown: the things, then each group and its
    requirements."""
    lines = [
        BEGIN,
        "\n",
        textwrap.fill(
            "The things: " + ", ".join(things()) + ".",
            72,
        )
        + "\n",
    ]
    group = None
    for requirement in requirements():
        if requirement["group"] != group:
            group = requirement["group"]
            lines.append(f"\n**{group}**\n\n")
        text = requirement["text"]
        if "held_by" in requirement:
            holder = requirement["held_by"]
            text += (
                " Not tested: nothing holds it."
                if holder == "nothing"
                else f" Not tested: held by {holder}."
            )
        lines.append(
            textwrap.fill(
                text, 72, initial_indent="- ", subsequent_indent="  "
            )
            + "\n"
        )
    lines.append("\n" + END)
    return "".join(lines)


def written(document: str) -> str:
    """The document with its section replaced by the one written now."""
    before, rest = document.split(BEGIN)
    after = rest.split(END)[1]
    return before + section() + after


if __name__ == "__main__":
    ARCHITECTURE.write_text(written(ARCHITECTURE.read_text()))
