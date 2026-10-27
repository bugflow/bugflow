"""Parse the files of a deployment.

A deployment is a set of text files held in the database. This module
parses them into what a worker reads: reviewers, each reviewer's
policies and doctrine, the pace layers, each reviewer's profiles, and
the glossary files.

Every problem in a deployment is collected and reported in one
``PolicyDeploymentError``, so a sender sees all of them in one attempt.
"""

import re
import tomllib
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from bugflow.method.domain.errors import PolicyDeploymentError
from bugflow.method.domain.models.doctrine import Doctrine
from bugflow.method.domain.models.pace_layer import PaceLayer
from bugflow.method.domain.models.policy_deployment import PolicyDeployment
from bugflow.method.domain.models.policy_text import PolicyText
from bugflow.method.infrastructure.doctrine_directory import joined
from bugflow.method.infrastructure.pace_layer_file import parse_topology
from bugflow.method.infrastructure.policy_files import parse_policy, source_of
from bugflow.method.infrastructure.reviewer_packages import (
    MANIFEST,
    MANIFESTS,
    DomainSpecificReviewAgent,
    parse_agent,
)

#: The file beside the reviewers that declares the pace layers.
TOPOLOGY = "pace-layers.toml"
#: The file that said what each repository was reviewed for, which ADR
#: 008 retires: each gnome's setting on a repository says it.
DECLARATIONS = "declarations.toml"
#: The file beside the reviewers that names each reviewer's profiles.
#: Optional.
PROFILES = "profiles.toml"
#: The profile every reviewer has, which the profiles file may define
#: and otherwise holds every policy of the reviewer this server answers.
DEFAULT_PROFILE = "default"
#: What a profile's name may be.
_PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
#: The directory of words documents the binding copies in. Optional.
GLOSSARY = "glossary"
#: The names a glossary file may have.
GLOSSARY_SUFFIXES = (".md", ".txt", ".org")


@dataclass(frozen=True, kw_only=True)
class ParsedDeployment:
    """The parsed content of one deployment.

    ``policies`` and ``doctrine`` are keyed by agent id. An agent with
    no policy files has an empty mapping, and an agent with no doctrine
    files has no entry in ``doctrine``.
    """

    agents: Mapping[str, DomainSpecificReviewAgent]
    policies: Mapping[str, Mapping[str, PolicyText]]
    doctrine: Mapping[str, Doctrine]
    layers: Mapping[str, PaceLayer]
    #: By agent id: the text a judge's fingerprint hashes for that
    #: agent's policies. Equal to ``policy_source`` of the same files
    #: in a directory.
    policy_sources: Mapping[str, str]
    #: By agent id: the text that agent's corpus version hashes: the
    #: manifest, then the policy source, then each doctrine file.
    prose: Mapping[str, str]
    #: The text of each file under glossary/, by path, in path order.
    glossary: Mapping[str, str] = field(default_factory=dict)
    #: Each reviewer's profiles, by agent id then profile name: the
    #: policies a repository set to that profile is judged on. Every
    #: reviewer has ``default``.
    profiles: Mapping[str, Mapping[str, tuple[str, ...]]] = field(
        default_factory=dict
    )


def _in_glossary(path: str) -> bool:
    """Whether the path is under the glossary directory."""
    return PurePosixPath(path).parts[0] == GLOSSARY


def _kind(path: str) -> tuple[str, str, str] | None:
    """Classify a path as (agent directory, kind, place), or None if the
    path is not one a server reads.

    The kinds are "manifest", "policy" and "doctrine". The place is the
    directory that holds a policy's or a doctrine's directory: the
    agent's directory, or the ``references`` directory of one of its
    skills, which holds a copy. A manifest's place is the agent's
    directory. The files beside the reviewers belong to no agent and
    are handled apart, and so are the glossary files.
    """
    parts = PurePosixPath(path).parts
    if parts[0] == GLOSSARY:
        return None
    if len(parts) == 2 and parts[1] in MANIFESTS:
        return parts[0], "manifest", parts[0]
    if not parts[-1].endswith(".md"):
        return None
    if len(parts) == 6 and parts[1] == "skills" and parts[3] == "references":
        place = "/".join(parts[:4])
    elif len(parts) == 3:
        place = parts[0]
    else:
        return None
    if parts[-2] == "policies":
        return parts[0], "policy", place
    if parts[-2] == "doctrine":
        return parts[0], "doctrine", place
    return None


def parse_deployment(
    deployment: PolicyDeployment,
    checks: Collection[str] | None = None,
    subjects: Collection[str] | None = None,
) -> ParsedDeployment:
    """Parse every file of the deployment. ``checks`` names the checks
    this server has, and ``subjects`` the subjects it renders, if the
    caller knows them.

    Raises ``PolicyDeploymentError`` listing every problem found: a path
    the server does not read, a glossary file of another name, a
    manifest or policy or topology that does not parse, two agents with
    one id, two manifests in one directory, two policies with one id in
    one agent, policy or doctrine files in a directory that has no
    manifest, policy or doctrine files of one agent in two skills and
    none in its own directory, and a profile naming a policy its
    reviewer does not hold, a checked policy no manifest gives a check,
    or a policy whose subject this server does not render.

    A declarations file, which ADR 008 retires, is passed over: a
    deployment in force from before it may carry one, and is read
    without it. ``refuse_retired`` refuses one in a new deployment.
    """
    problems: list[str] = []
    by_directory: dict[str, DomainSpecificReviewAgent] = {}
    agents: dict[str, DomainSpecificReviewAgent] = {}
    manifests: dict[str, str] = {}
    layers: dict[str, PaceLayer] = {}
    glossary: dict[str, str] = {}

    for one in deployment.files:
        if _in_glossary(one.path):
            if one.path.endswith(GLOSSARY_SUFFIXES):
                glossary[one.path] = one.text
            else:
                problems.append(
                    f"{one.path}: a glossary file ends in "
                    f"{', '.join(GLOSSARY_SUFFIXES)}"
                )
            continue
        if one.path == TOPOLOGY:
            try:
                layers = parse_topology(Path(one.path), one.text)
            except ValueError as exc:
                problems.append(str(exc))
            continue
        if one.path == DECLARATIONS:
            continue
        if one.path == PROFILES:
            # Parsed after the policies, which it names.
            continue
        kind = _kind(one.path)
        if kind is None:
            problems.append(f"{one.path}: not a file a server reads")
        elif kind[1] == "manifest":
            try:
                agent = parse_agent(Path(one.path), one.text, checks)
            except ValueError as exc:
                problems.append(f"{kind[0]}/{exc}")
                continue
            if kind[0] in by_directory:
                problems.append(f"{one.path}: a second manifest in {kind[0]}/")
                continue
            if agent.agent_id in agents:
                problems.append(
                    f"{one.path}: a second agent with the id {agent.agent_id}"
                )
                continue
            agents[agent.agent_id] = agent
            by_directory[kind[0]] = agent
            manifests[agent.agent_id] = one.text

    policies: dict[str, dict[str, PolicyText]] = {
        agent_id: {} for agent_id in agents
    }
    policy_texts: dict[str, list[str]] = {}
    doctrine_parts: dict[str, list[str]] = {}
    originals = _originals(deployment, by_directory, problems)
    for one in deployment.files:
        kind = _kind(one.path)
        if kind is None or kind[1] == "manifest":
            continue
        owner = by_directory.get(kind[0])
        if owner is None:
            problems.append(f"{one.path}: {kind[0]}/{MANIFEST} is missing")
            continue
        if kind[2] != originals.get(kind[0]):
            # A skill's copy of a file whose original is read.
            continue
        if kind[1] == "doctrine":
            doctrine_parts.setdefault(owner.agent_id, []).append(one.text)
            continue
        policy_texts.setdefault(owner.agent_id, []).append(one.text)
        try:
            policy = parse_policy(PurePosixPath(one.path).name, one.text)
        except ValueError as exc:
            problems.append(f"{kind[2]}/policies/{exc}")
            continue
        if policy.policy_id in policies[owner.agent_id]:
            problems.append(
                f"{one.path}: a second policy with the id {policy.policy_id}"
            )
        else:
            policies[owner.agent_id][policy.policy_id] = policy

    unanswerable = _unanswerable(agents, policies, subjects)
    profiles = _profiles(
        deployment.text_of(PROFILES),
        {
            agent_id: tuple(
                policy_id
                for policy_id in agent.policies
                if policy_id in policies[agent_id]
                or policy_id in {one.policy_id for one in agent.checks}
            )
            for agent_id, agent in agents.items()
        },
        unanswerable,
        problems,
    )
    if problems:
        raise PolicyDeploymentError("; ".join(problems))
    # deployment.files is in path order, so each agent's policy texts
    # and doctrine texts are already in filename order.
    policy_sources = {
        agent_id: source_of(policy_texts.get(agent_id, []))
        for agent_id in agents
    }
    return ParsedDeployment(
        agents=agents,
        policies=policies,
        policy_sources=policy_sources,
        prose={
            agent_id: manifests[agent_id]
            + policy_sources[agent_id]
            + "".join(doctrine_parts.get(agent_id, []))
            for agent_id in agents
        },
        doctrine={
            agent_id: joined(parts)
            for agent_id, parts in doctrine_parts.items()
        },
        layers=layers,
        glossary=glossary,
        profiles=profiles,
    )


def _originals(
    deployment: PolicyDeployment,
    by_directory: Mapping[str, DomainSpecificReviewAgent],
    problems: list[str],
) -> dict[str, str]:
    """The place each agent's policies and doctrine are read from, by
    the agent's directory: the directory itself when it holds any, or
    else the ``references`` directory of its one skill. Each skill's
    copy is passed over.

    An agent with the files in two skills and none in its directory
    gets no place, and the problem is added to ``problems``: nothing
    says which copy is the original.
    """
    places: dict[str, set[str]] = {}
    for one in deployment.files:
        kind = _kind(one.path)
        if kind is None or kind[1] == "manifest":
            continue
        if kind[0] not in by_directory:
            continue
        places.setdefault(kind[0], set()).add(kind[2])
    originals: dict[str, str] = {}
    for directory, found in places.items():
        if directory in found:
            originals[directory] = directory
        elif len(found) == 1:
            originals[directory] = next(iter(found))
        else:
            problems.append(
                f"{directory}/: the policies and the doctrine are in "
                f"{' and '.join(place + '/' for place in sorted(found))}, "
                f"and {directory}/ has no policies/ or doctrine/ of its own"
            )
    return originals


def _unanswerable(
    agents: Mapping[str, DomainSpecificReviewAgent],
    policies: Mapping[str, Mapping[str, PolicyText]],
    subjects: Collection[str] | None,
) -> dict[str, str]:
    """The policies this server holds and cannot answer, each with why:
    a checked policy that no manifest gives a check, and a judged
    policy whose subject is not among ``subjects``, when they are
    known. A gnome may hold such a policy for another consumer; a
    profile naming one is refused, and a default profile leaves it out.
    """
    checked = {
        one.policy_id for agent in agents.values() for one in agent.checks
    }
    reasons: dict[str, str] = {}
    for of_agent in policies.values():
        for policy_id, policy in of_agent.items():
            if policy_id in checked:
                continue
            if policy.checked:
                reasons[policy_id] = (
                    f"{policy_id} is answered by a check, and no manifest "
                    "gives it one this server has"
                )
            elif subjects is not None and policy.evidence not in subjects:
                reasons[policy_id] = (
                    f"{policy_id} reads {policy.evidence}, which this "
                    "server does not render"
                )
    return reasons


def _profiles(
    text: str | None,
    held: Mapping[str, tuple[str, ...]],
    unanswerable: Mapping[str, str],
    problems: list[str],
) -> dict[str, dict[str, tuple[str, ...]]]:
    """Parse the profiles file, adding each problem found to
    ``problems``, and give every reviewer its ``default``.

    The file has one table for each profile, under the reviewer's id::

        [profile.prose.default]
        policies = ["P-01", "P-02"]

    ``held`` gives each reviewer's policies, by agent id: those its
    manifest lists that the deployment holds, by a file or a check. A
    profile may name only policies its own reviewer holds, and none this
    server cannot answer. A reviewer whose ``default`` the file does not
    define has one holding every policy of it that this server answers,
    so a binding with no profiles file has one profile for each
    reviewer.
    """
    found: dict[str, dict[str, tuple[str, ...]]] = {
        agent_id: {} for agent_id in held
    }
    document: dict[str, object] = {}
    if text is not None:
        try:
            document = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            problems.append(f"{PROFILES}: {exc}")
    other = sorted(set(document) - {"profile"})
    if other:
        problems.append(
            f"{PROFILES}: {', '.join(other)} is not a table this file "
            "has; it has profile"
        )
    by_agent = document.get("profile", {})
    if not isinstance(by_agent, dict):
        problems.append(f"{PROFILES}: profile must be a table")
        by_agent = {}
    for agent_id, named in sorted(by_agent.items()):
        if agent_id not in held:
            problems.append(
                f"{PROFILES}: {agent_id} is not a reviewer this "
                "deployment holds"
            )
            continue
        if not isinstance(named, dict):
            problems.append(f"{PROFILES}: profile.{agent_id} must be a table")
            continue
        for name, table in sorted(named.items()):
            where = f"{PROFILES}: profile.{agent_id}.{name}"
            if not _PROFILE_NAME.match(name):
                problems.append(
                    f"{where}: a profile's name is lower case letters, "
                    "digits and hyphens"
                )
                continue
            if not isinstance(table, dict):
                problems.append(f"{where} must be a table")
                continue
            unknown = sorted(set(table) - {"policies"})
            if unknown:
                problems.append(
                    f"{where}: {', '.join(unknown)} is not policies"
                )
            value = table.get("policies", [])
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                problems.append(f"{where}: policies must be a list of names")
                continue
            missing = sorted(set(value) - set(held[agent_id]))
            if missing:
                problems.append(
                    f"{where}: {', '.join(missing)} is not a policy of "
                    f"{agent_id}"
                )
            for one in value:
                if one in unanswerable:
                    problems.append(f"{where}: {unanswerable[one]}")
            found[agent_id][name] = tuple(dict.fromkeys(value))
    for agent_id, policy_ids in held.items():
        found[agent_id].setdefault(
            DEFAULT_PROFILE,
            tuple(p for p in policy_ids if p not in unanswerable),
        )
    return found


def refuse_retired(deployment: PolicyDeployment) -> None:
    """Refuse a new deployment that carries a file ADR 008 retires."""
    if deployment.text_of(DECLARATIONS) is not None:
        raise PolicyDeploymentError(
            f"{DECLARATIONS} is retired by ADR 008: a binding names its "
            f"profiles in {PROFILES}, and an operator sets each gnome on "
            "each repository"
        )


class ParsedPolicyDeploymentCheck:
    """Implements ``PolicyDeploymentCheckService`` by parsing every file
    of the deployment with ``parse_deployment``. ``checks`` names the
    checks this server has, and ``subjects`` the subjects it renders,
    if the application knows them."""

    def __init__(
        self,
        checks: Collection[str] | None = None,
        subjects: Collection[str] | None = None,
    ) -> None:
        self._checks = checks
        self._subjects = subjects

    def check(self, deployment: PolicyDeployment) -> None:
        refuse_retired(deployment)
        parse_deployment(deployment, self._checks, self._subjects)
