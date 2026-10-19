"""Parse the files of a deployment.

A deployment is a set of text files held in the database. This module
parses them into what a worker reads: reviewers, each reviewer's
policies and doctrine, the pace layers, what each repository
declares, and the glossary files.

Every problem in a deployment is collected and reported in one
``PolicyDeploymentError``, so a sender sees all of them in one attempt.
"""

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
#: The file beside the reviewers that says what each repository is
#: reviewed for. Optional.
DECLARATIONS = "declarations.toml"
#: The directory of words documents the binding copies in. Optional.
GLOSSARY = "glossary"
#: The names a glossary file may have.
GLOSSARY_SUFFIXES = (".md", ".txt", ".org")


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
    #: The text of each file under glossary/, by path, in path order.
    glossary: Mapping[str, str] = field(default_factory=dict)


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
    none in its own directory, and a declaration naming a policy or
    process the deployment does not hold, a checked policy no manifest
    gives a check, or a policy whose subject this server does not
    render.
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

    declarations = deployment.text_of(DECLARATIONS)
    declared = (
        None
        if declarations is None
        else _declared(
            declarations,
            # A policy a check answers need have no file. Its id is
            # known from the manifest that names it.
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
            unanswerable=_unanswerable(agents, policies, subjects),
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
        glossary=glossary,
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
    declaration naming one is refused.
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


def _declared(
    text: str,
    known_policies: set[str],
    known_processes: set[str],
    problems: list[str],
    unanswerable: Mapping[str, str] | None = None,
) -> tuple[RepositoryDeclaration, ...]:
    """Parse the declarations file, adding each problem found to
    ``problems``. ``unanswerable`` gives, for a policy the deployment
    holds and this server cannot answer, the reason a declaration
    naming it is refused.

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
            for one in value:
                if unanswerable and one in unanswerable:
                    problems.append(f"{where}: {unanswerable[one]}")
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
        parse_deployment(deployment, self._checks, self._subjects)
