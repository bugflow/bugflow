"""Read a binding's editor from its files.

``pr-comment-editor.md`` is a header, a line of three dashes, and the
instructions::

    model_class: medium
    ---
    You edit the draft of a review comment ...

Each file under ``pr-comment-editor/examples/`` is one example: a
header, a line of three dashes, and the comment. The file's name says
what it shows, ``good-01-one-fix.md`` or ``bad-01-every-finding.md``,
and the header's one line says why::

    why: Three findings, the one that blocks first, each with its fix.
    ---
    The comment.

``docs/policy-package.md`` specifies both files. Nothing here knows what
a prompt is for.
"""

import re
from pathlib import PurePosixPath

from bugflow.method.domain.models.editor import (
    Editor,
    EditorExample,
    ExampleKind,
)

#: The binding's editor file, beside the reviewers.
EDITOR = "pr-comment-editor.md"
#: The directory of the editor's examples.
EXAMPLES = "pr-comment-editor/examples"
#: An example's file name: its kind, a number, and a name.
_EXAMPLE_NAME = re.compile(r"^(?P<kind>good|bad)-\d+-[a-z0-9-]+\.md$")
#: The header lines ``pr-comment-editor.md`` has, one value each.
_EDITOR_FIELDS = ("model_class",)
#: The header lines an example has, one value each.
_EXAMPLE_FIELDS = ("why",)


def _header(name: str, text: str, fields: tuple[str, ...]) -> dict[str, str]:
    """The header's lines as a mapping. Each line is ``key: value``,
    each key one of ``fields``, and none given twice."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"{name}: header line {line!r} is not key: value")
        key, value = line.split(":", 1)
        if key not in fields:
            raise ValueError(
                f"{name}: {key!r} is not a line this file has; it has "
                f"{', '.join(fields)}"
            )
        if key in found:
            raise ValueError(f"{name}: two {key} lines")
        found[key] = value.strip()
    missing = [key for key in fields if key not in found]
    if missing:
        raise ValueError(f"{name}: no {', '.join(missing)} line")
    return found


def _split(name: str, text: str) -> tuple[str, str]:
    """The header and the body, either side of the --- line. A file
    that opens with the line has an empty header."""
    if text.startswith("---\n"):
        return "", text[len("---\n") :]
    header, separator, body = text.partition("\n---\n")
    if not separator:
        raise ValueError(f"{name}: no --- line after the header")
    return header, body


def parse_editor(
    name: str, text: str, examples: tuple[EditorExample, ...] = ()
) -> Editor:
    """The editor a file's text holds, where ``name`` is the file's
    path, with the examples already read.

    Raises ``ValueError``, opening with the name, for text that is not
    an editor file, and ``PolicyDeploymentError`` for one whose values
    the editor refuses.
    """
    header, body = _split(name, text)
    fields = _header(name, header, _EDITOR_FIELDS)
    return Editor(
        model_class=fields["model_class"],
        instructions=body.strip("\n"),
        examples=examples,
    )


def example_kind(path: str) -> ExampleKind:
    """What an example's file name says it shows.

    Raises ``ValueError`` for a name of another shape.
    """
    found = _EXAMPLE_NAME.match(PurePosixPath(path).name)
    if found is None:
        raise ValueError(
            f"{path}: an example is named good-NN-name.md or bad-NN-name.md"
        )
    kind: ExampleKind = "good" if found.group("kind") == "good" else "bad"
    return kind


def parse_example(path: str, text: str) -> EditorExample:
    """The example a file's text holds, where ``path`` is the file's
    path under the deployment.

    Raises ``ValueError``, opening with the path, for text that is not
    an example, and ``PolicyDeploymentError`` for one with nothing in
    it.
    """
    kind = example_kind(path)
    header, body = _split(path, text)
    fields = _header(path, header, _EXAMPLE_FIELDS)
    return EditorExample(
        name=PurePosixPath(path).stem,
        kind=kind,
        why=fields["why"],
        text=body.strip("\n"),
    )
