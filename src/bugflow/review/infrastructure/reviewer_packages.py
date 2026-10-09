"""Read installed reviewers from the directories that hold them.

A reviewer is a directory. It holds a manifest named ``reviewer.md``,
and may hold a ``policies`` directory and a ``doctrine`` directory.

A manifest is a header, a line of three dashes, and then the reviewer's
instructions in prose. The header is lines of the form ``key: value``::

    agent_id: prose
    summary: What a change says about itself
    runner: judge
    governs: yes
    policies: P-01, P-02, P-04
    checks: em-dash P-04 RULE-21
    ---
    The reviewer's instructions.

``agent_id``, ``summary``, ``runner`` and ``governs`` are required.

``checks`` says which of the reviewer's policies a check of this server
answers. Each entry is three words: the check's name, the policy's id,
and the id of the doctrine clause the findings cite. Entries are
separated by commas. The check must be one this server has, and the
policy must be one of the reviewer's.

Nothing here builds a prompt or runs anything.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from bugflow.review.domain.errors import ReviewAgentError
from bugflow.review.domain.values.checked_policy import CHECKS

_REQUIRED = ("agent_id", "summary", "runner", "governs")
_SEPARATOR = "\n---\n"
#: The name of a reviewer's manifest file.
MANIFEST = "reviewer.md"


@dataclass(frozen=True)
class CheckedPolicy:
    """One policy of a reviewer that a check answers."""

    #: The check's name, one of ``CHECKS``.
    check: str
    policy_id: str
    #: The id of the doctrine clause the check's findings cite.
    clause: str


@dataclass(frozen=True)
class DomainSpecificReviewAgent:
    """One reviewer, as its directory describes it."""

    agent_id: str
    summary: str
    #: The name of the code that runs it: the judge, or a runner for a
    #: checkout agent.
    runner: str
    #: Whether its verdict decides a repository's label, unless the
    #: repository is set up otherwise.
    governs: bool
    #: The ids of its policies. Empty if its instructions are all it
    #: has.
    policies: tuple[str, ...]
    directory: Path
    #: The prose after the header.
    description: str
    #: The policies that a check answers.
    checks: tuple[CheckedPolicy, ...] = ()

    @property
    def policy_dir(self) -> Path:
        return self.directory / "policies"

    @property
    def doctrine_dir(self) -> Path:
        return self.directory / "doctrine"


def _flag(name: str, field: str, value: str) -> bool:
    if value not in ("yes", "no"):
        raise ValueError(f"{name}: {field} is {value!r}, not yes or no")
    return value == "yes"


def _checks(
    name: str, value: str, policies: tuple[str, ...]
) -> tuple[CheckedPolicy, ...]:
    """Read the ``checks`` field of a header."""
    checks: list[CheckedPolicy] = []
    for entry in value.split(","):
        words = entry.split()
        if not words:
            continue
        if len(words) != 3:
            raise ValueError(
                f"{name}: check {entry.strip()!r} is not a check's name, "
                "a policy id and a clause id"
            )
        check, policy_id, clause = words
        if check not in CHECKS:
            raise ValueError(
                f"{name}: {check!r} is not a check this server has; "
                f"it has {', '.join(CHECKS)}"
            )
        if policy_id not in policies:
            raise ValueError(
                f"{name}: check {check} answers {policy_id}, which is "
                "not among the reviewer's policies"
            )
        checks.append(
            CheckedPolicy(check=check, policy_id=policy_id, clause=clause)
        )
    return tuple(checks)


def parse_agent(path: Path, text: str) -> DomainSpecificReviewAgent:
    """Read one manifest. ``path`` is the manifest's path, and ``text``
    its content.

    Raises ``ValueError``, naming the file, if the manifest has no line
    of three dashes, a header line that is not ``key: value``, a
    required field missing, or a field that cannot be read.
    """
    name = path.name
    header, separator, description = text.partition(_SEPARATOR)
    if not separator:
        raise ValueError(f"{name}: no --- line separating header from prose")
    fields: dict[str, str] = {}
    for line in header.splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"{name}: header line {line!r} is not key: value")
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    missing = [field for field in _REQUIRED if field not in fields]
    if missing:
        raise ValueError(f"{name}: header is missing {', '.join(missing)}")
    policies = tuple(
        policy.strip()
        for policy in fields.get("policies", "").split(",")
        if policy.strip()
    )
    return DomainSpecificReviewAgent(
        agent_id=fields["agent_id"],
        summary=fields["summary"],
        runner=fields["runner"],
        governs=_flag(name, "governs", fields["governs"]),
        policies=policies,
        directory=path.parent,
        description=description.strip("\n"),
        checks=_checks(name, fields.get("checks", ""), policies),
    )


def load_agents(directory: Path) -> dict[str, DomainSpecificReviewAgent]:
    """Read every reviewer under ``directory``, and return them by agent
    id.

    A directory inside it with no manifest is not a reviewer and is
    passed over. If ``directory`` holds no reviewer, or does not exist,
    the result is empty: a server with no reviewer installed is allowed.

    Raises ``ReviewAgentError`` if two reviewers have the same agent id.
    """
    agents: dict[str, DomainSpecificReviewAgent] = {}
    for manifest in sorted(directory.glob(f"*/{MANIFEST}")):
        agent = parse_agent(manifest, manifest.read_text())
        if agent.agent_id in agents:
            raise ReviewAgentError(f"two agents claim {agent.agent_id}")
        agents[agent.agent_id] = agent
    return agents


def installed(
    names: Iterable[str],
    agents: Mapping[str, DomainSpecificReviewAgent],
) -> dict[str, DomainSpecificReviewAgent]:
    """Pick the named reviewers out of ``agents``. If no name is given,
    all of them are returned.

    Raises ``ReviewAgentError`` if a named reviewer is not among them.
    A server that was told to run a reviewer it does not have must not
    start as if it had.
    """
    available = dict(agents)
    wanted = [name for name in names]
    if not wanted:
        return available
    missing = [name for name in wanted if name not in available]
    if missing:
        raise ReviewAgentError(
            f"not installed: {', '.join(sorted(missing))}; "
            f"available: {', '.join(sorted(available))}"
        )
    return {name: available[name] for name in wanted}
