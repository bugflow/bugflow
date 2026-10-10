"""Parse the files of a deployment.

A deployment is a set of text files held in the database. This module
parses them into what a worker reads: reviewers, each reviewer's
policies and doctrine, the pace layers, and what each repository
declares.

Every problem in a deployment is collected and reported in one
``PolicyDeploymentError``, so a sender sees all of them in one attempt.
"""

import tomllib
from collections.abc import Collection, Mapping
from dataclasses import dataclass
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
    DomainSpecificReviewAgent,
    parse_agent,
)

#: The file beside the reviewers that declares the pace layers.
TOPOLOGY = "pace-layers.toml"
#: The file beside the reviewers that says what each repository is
#: reviewed for. Optional.
DECLARATIONS = "declarations.toml"


@dataclass(frozen=True, kw_only=True)
class RepositoryDeclaration:
    """What one repository is reviewed for, as a deployment declares it.

    Plain data: which policies are judged and which processes are
    dispatched, by name. Writing it where the declarations are kept is
    the application's.
    """

    forge: str
    #: As ``owner/name``.
    repo: str
    policies: tuple[str, ...]
    processes: tuple[str, ...]


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
    #: What each repository is reviewed for, in repository order. None
    #: if the deployment has no declarations file, which leaves the
    #: server's declarations as they are. An empty tuple is a file that
    #: declares no repository.
    declared: tuple[RepositoryDeclaration, ...] | None = None


def _kind(path: str) -> tuple[str, str] | None:
    """Classify a path as (agent directory, kind), or None if the path
    is not one a server reads.

    The kinds are "manifest", "policy" and "doctrine". The files beside
    the reviewers belong to no agent and are handled apart.
    """
    parts = PurePosixPath(path).parts
    if len(parts) == 2 and parts[1] == MANIFEST:
        return parts[0], "manifest"
    if len(parts) == 3 and parts[2].endswith(".md"):
        if parts[1] == "policies":
            return parts[0], "policy"
        if parts[1] == "doctrine":
            return parts[0], "doctrine"
    return None


def parse_deployment(
    deployment: PolicyDeployment, checks: Collection[str] | None = None
) -> ParsedDeployment:
    """Parse every file of the deployment. ``checks`` names the checks
    this server has, if the caller knows them.

    Raises ``PolicyDeploymentError`` listing every problem found: a
    path the server does not read, a manifest or policy or topology
    that does not parse, two agents with one id, two policies with one
    id in one agent, policy or doctrine files in a directory that has
    no manifest, and a declaration naming a policy or process the
    deployment does not hold.
    """
    problems: list[str] = []
    by_directory: dict[str, DomainSpecificReviewAgent] = {}
    agents: dict[str, DomainSpecificReviewAgent] = {}
    manifests: dict[str, str] = {}
    layers: dict[str, PaceLayer] = {}

    for one in deployment.files:
        if one.path == TOPOLOGY:
            try:
                layers = parse_topology(Path(one.path), one.text)
            except ValueError as exc:
                problems.append(str(exc))
            continue
        if one.path == DECLARATIONS:
            # Parsed after the policies and the layers, which it names.
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
    for one in deployment.files:
        kind = _kind(one.path)
        if kind is None or kind[1] == "manifest":
            continue
        owner = by_directory.get(kind[0])
        if owner is None:
            problems.append(f"{one.path}: {kind[0]}/{MANIFEST} is missing")
            continue
        if kind[1] == "doctrine":
            doctrine_parts.setdefault(owner.agent_id, []).append(one.text)
            continue
        policy_texts.setdefault(owner.agent_id, []).append(one.text)
        try:
            policy = parse_policy(PurePosixPath(one.path).name, one.text)
        except ValueError as exc:
            problems.append(f"{kind[0]}/policies/{exc}")
            continue
        if policy.policy_id in policies[owner.agent_id]:
            problems.append(
                f"{one.path}: a second policy with the id {policy.policy_id}"
            )
        else:
            policies[owner.agent_id][policy.policy_id] = policy

    declarations = deployment.text_of(DECLARATIONS)
    declared = (
        None
        if declarations is None
        else _declared(
            declarations,
            # A policy a check answers has no file. Its id is known
            # from the manifest that names it.
            known_policies={
                policy_id
                for of_agent in policies.values()
                for policy_id in of_agent
            }
            | {
                checked.policy_id
                for agent in agents.values()
                for checked in agent.checks
            },
            known_processes={
                process.name
                for layer in layers.values()
                for process in layer.processes
            },
            problems=problems,
        )
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
        declared=declared,
    )


def _declared(
    text: str,
    known_policies: set[str],
    known_processes: set[str],
    problems: list[str],
) -> tuple[RepositoryDeclaration, ...]:
    """Parse the declarations file, adding each problem found to
    ``problems``.

    The file has one table for each repository::

        [repository."owner/name"]
        policies = ["P-01"]
        processes = ["evaluate-pull-request"]

    The key is ``owner/name`` for a repository on GitHub, or
    ``forge:owner/name``. Each list may be left out, which declares
    none. A policy must be one this deployment holds, by a file or by a
    manifest's ``checks`` line, and a process must be one the
    deployment's topology declares.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        problems.append(f"{DECLARATIONS}: {exc}")
        return ()
    other = sorted(set(document) - {"repository"})
    if other:
        problems.append(
            f"{DECLARATIONS}: {', '.join(other)} is not a table this "
            "file has; it has repository"
        )
    repositories = document.get("repository", {})
    if not isinstance(repositories, dict):
        problems.append(f"{DECLARATIONS}: repository must be a table")
        return ()
    found: list[RepositoryDeclaration] = []
    for name, table in sorted(repositories.items()):
        where = f"{DECLARATIONS}: repository {name!r}"
        forge, _, repo = name.partition(":")
        if not repo:
            forge, repo = "github", name
        if repo.count("/") != 1 or not all(repo.split("/")):
            problems.append(f"{where} is not owner/name or forge:owner/name")
            continue
        if not isinstance(table, dict):
            problems.append(f"{where} must be a table")
            continue
        unknown = sorted(set(table) - {"policies", "processes"})
        if unknown:
            problems.append(
                f"{where}: {', '.join(unknown)} is not policies or processes"
            )
        named: dict[str, tuple[str, ...]] = {}
        for key, known, kind in (
            ("policies", known_policies, "policy"),
            ("processes", known_processes, "process"),
        ):
            value = table.get(key, [])
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                problems.append(f"{where}: {key} must be a list of names")
                value = []
            missing = sorted(set(value) - known)
            if missing:
                problems.append(
                    f"{where}: {', '.join(missing)} is not a {kind} this "
                    "deployment holds"
                )
            named[key] = tuple(dict.fromkeys(value))
        found.append(
            RepositoryDeclaration(
                forge=forge,
                repo=repo,
                policies=named["policies"],
                processes=named["processes"],
            )
        )
    return tuple(found)


class ParsedPolicyDeploymentCheck:
    """Implements ``PolicyDeploymentCheckService`` by parsing every file
    of the deployment with ``parse_deployment``. ``checks`` names the
    checks this server has, if the application knows them."""

    def __init__(self, checks: Collection[str] | None = None) -> None:
        self._checks = checks

    def check(self, deployment: PolicyDeployment) -> None:
        parse_deployment(deployment, self._checks)
