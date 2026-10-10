"""Read judged policies from their files, one file per policy.

A file is a header, a line of three dashes, the instructions, a line
``=== calibration``, and what calibration has shown::

    policy_id: P-01
    subject: pull request
    summary: The pull request does one thing a reviewer can state
    model_class: medium
    evidence: scope
    quotable_name: title, description, commit messages or file paths
    graded: yes
    quotes_code: no
    clause: RULE-4 the pull request does one thing
    ---
    What the model is told, up to the calibration line.
    === calibration
    What measuring it has shown.

A clause line is its id, then the doctrine's name for it. The body's
lines are wrapped so that a policy can be read and its changes diffed;
a line that does not open a list item continues the line above it, the
way Markdown joins them, so what the model is given is the paragraph
rather than the wrapping.

Nothing here knows what a prompt is for.
"""

from collections.abc import Iterable
from pathlib import Path

from bugflow.method.domain.models.policy_text import (
    CEILINGS,
    EVIDENCE_KINDS,
    PolicyText,
)

# Header lines that are one value each, and must all be given.
_REQUIRED = (
    "policy_id",
    "subject",
    "summary",
    "model_class",
    "evidence",
    "quotable_name",
    "graded",
    "quotes_code",
)
# Header lines a policy may give, one value each.
_OPTIONAL = ("ceiling",)
_CALIBRATION = "\n=== calibration\n"


def unwrap(text: str) -> str:
    """The body's paragraphs, joined back from the lines they are
    wrapped to.

    A blank line separates paragraphs and a line opening with ``- ``
    opens a list item; anything else continues what came before it.
    """
    lines: list[str] = []
    for line in text.split("\n"):
        if not line:
            lines.append("")
        elif lines and lines[-1] and not line.startswith("- "):
            lines[-1] = f"{lines[-1]} {line}"
        else:
            lines.append(line)
    return "\n".join(lines)


def _ceiling(name: str, value: str) -> str:
    if value not in CEILINGS:
        raise ValueError(
            f"{name}: ceiling is {value!r}, not {' or '.join(CEILINGS)}"
        )
    return value


def _evidence(name: str, value: str) -> str:
    if value not in EVIDENCE_KINDS:
        raise ValueError(
            f"{name}: evidence {value!r} is not one of "
            f"{', '.join(EVIDENCE_KINDS)}"
        )
    return value


def _flag(name: str, field: str, value: str) -> bool:
    if value not in ("yes", "no"):
        raise ValueError(f"{name}: {field} is {value!r}, not yes or no")
    return value == "yes"


def _header(name: str, text: str) -> tuple[dict[str, str], dict[str, str]]:
    fields: dict[str, str] = {}
    clauses: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"{name}: header line {line!r} is not key: value")
        key, value = line.split(":", 1)
        value = value.strip()
        if key == "clause":
            clause, _, clause_name = value.partition(" ")
            if not clause_name:
                raise ValueError(
                    f"{name}: clause line {value!r} is not an id and a name"
                )
            clauses[clause] = clause_name
        elif key in _REQUIRED or key in _OPTIONAL:
            if key in fields:
                raise ValueError(f"{name}: two {key} lines")
            fields[key] = value
        else:
            raise ValueError(f"{name}: {key!r} is not a policy field")
    return fields, clauses


def load_policy(path: Path) -> PolicyText:
    """The policy a file holds."""
    return parse_policy(path.name, path.read_text())


def parse_policy(name: str, text: str) -> PolicyText:
    """The policy a file's text holds, where ``name`` is the file's
    name. The text need not be on disk: a deployment holds it in the
    database.

    Raises ``ValueError``, opening with the name, for text that is not
    a policy.
    """
    header, separator, rest = text.partition("\n---\n")
    if not separator:
        raise ValueError(f"{name}: no --- line after the header")
    fields, clauses = _header(name, header)
    missing = [key for key in _REQUIRED if key not in fields]
    if missing:
        raise ValueError(f"{name}: no {', '.join(missing)} line")
    if not clauses:
        raise ValueError(f"{name}: no clause line")
    instructions, found, calibration = rest.partition(_CALIBRATION)
    if not found:
        raise ValueError(f"{name}: no === calibration line")
    if not name.startswith(fields["policy_id"]):
        raise ValueError(
            f"{name}: names {fields['policy_id']}, which its filename "
            "does not open with"
        )
    return PolicyText(
        policy_id=fields["policy_id"],
        subject=fields["subject"],
        summary=fields["summary"],
        model_class=fields["model_class"],
        evidence=_evidence(name, fields["evidence"]),
        quotable_name=fields["quotable_name"],
        graded=_flag(name, "graded", fields["graded"]),
        quotes_code=_flag(name, "quotes_code", fields["quotes_code"]),
        ceiling=_ceiling(name, fields.get("ceiling", "fail")),
        clauses=clauses,
        instructions=unwrap(instructions.strip("\n")),
        calibration=unwrap(calibration.strip("\n")),
    )


def load_policies(directory: Path) -> dict[str, PolicyText]:
    """Every policy in the directory, by id, in filename order.

    A directory holding no policy, or one that is not there, gives
    none: a server with no policy judges nothing.

    Raises ``ValueError`` if two files claim one policy id.
    """
    policies: dict[str, PolicyText] = {}
    for path in sorted(directory.glob("*.md")):
        policy = load_policy(path)
        if policy.policy_id in policies:
            raise ValueError(f"{path.name}: {policy.policy_id} twice")
        policies[policy.policy_id] = policy
    return policies


def policy_source(directory: Path) -> str:
    """What the model is asked, from every policy file in the directory,
    for a judge's fingerprint.

    Everything below a file's calibration line is dropped, because it
    is dropped before the prompt is built too. Hashing it would make
    writing a measurement down change the fingerprint the measurement
    was taken under.
    """
    return source_of(
        path.read_text() for path in sorted(directory.glob("*.md"))
    )


def source_of(texts: Iterable[str]) -> str:
    """The same as ``policy_source``, for policy texts that are not
    files: each text up to its calibration line, joined in the order
    given. The caller passes them in filename order."""
    return "".join(text.partition(_CALIBRATION)[0] for text in texts)
