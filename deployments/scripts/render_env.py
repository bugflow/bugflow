"""Render the settings templates into the files the compositions read.

Usage::

    render_env.py VALUES [DIRECTORY]

VALUES is a file of ``name=value`` lines, one for each template
variable. Blank lines and lines beginning ``#`` are skipped. A name
with dots in it is a value inside a mapping, so
``project_oidc_clients.policies-pipeline.client_id=abc`` is the
``client_id`` of the ``policies-pipeline`` entry of
``project_oidc_clients``.

Each ``deployments/env/NAME.env.j2`` is written to
``DIRECTORY/NAME.env``, readable by its owner alone. DIRECTORY is
``env`` at the root of the repository unless given.

A template that names a variable VALUES does not hold, and gives it no
default, is not rendered: the script says which variable and exits
with status 1.
"""

import sys
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from jinja2.exceptions import UndefinedError

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "deployments" / "env"
SUFFIX = ".env.j2"


def values_from(text: str) -> dict[str, Any]:
    """Read ``name=value`` lines into the variables a template is
    rendered with."""
    values: dict[str, Any] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, _, value = line.partition("=")
        *mappings, last = name.strip().split(".")
        within = values
        for mapping in mappings:
            within = within.setdefault(mapping, {})
        within[last] = value.strip()
    return values


def render(values: dict[str, Any], directory: Path) -> list[Path]:
    """Write every template's file under ``directory`` and return the
    paths written.

    Raises ``UndefinedError`` if a template names a variable that has
    no value and no default.
    """
    templates = Environment(
        loader=FileSystemLoader(TEMPLATES),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,
    )
    rendered = {
        path.name.removesuffix(SUFFIX): templates.get_template(
            path.name
        ).render(values)
        for path in sorted(TEMPLATES.glob(f"*{SUFFIX}"))
    }
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in rendered.items():
        target = directory / f"{name}.env"
        target.touch(mode=0o600)
        target.chmod(0o600)
        target.write_text(text)
        written.append(target)
    return written


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 2):
        print("usage: render_env.py VALUES [DIRECTORY]", file=sys.stderr)
        return 2
    values = values_from(Path(argv[0]).read_text())
    directory = Path(argv[1]) if len(argv) == 2 else ROOT / "env"
    try:
        written = render(values, directory)
    except UndefinedError as exc:
        print(
            f"error: {exc.message}; {argv[0]} gives it no value",
            file=sys.stderr,
        )
        return 1
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
