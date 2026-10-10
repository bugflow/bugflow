"""The reviewers a program runs with, from the policy deployment in
force.

A program needs the same things whichever deployment they come from:
the reviewers, each reviewer's policies and doctrine, the pace layers,
and the texts that feed a corpus version. ``ReviewersInForce`` holds
them, and ``reviewers_in_force`` builds one from the deployment the
database says is in force, parsed with the checks this server has.
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass

from bugflow.method.domain.models.doctrine import Doctrine
from bugflow.method.domain.models.pace_layer import PaceLayer
from bugflow.method.domain.models.policy_deployment import PolicyDeployment
from bugflow.method.domain.models.policy_text import PolicyText
from bugflow.method.domain.repositories.doctrine import DoctrineRepository
from bugflow.method.domain.repositories.policy_deployment import (
    PolicyDeploymentRepository,
)
from bugflow.method.infrastructure.deployment_watch import DeployedFrom
from bugflow.method.infrastructure.fixed_doctrine import FixedDoctrine
from bugflow.method.infrastructure.no_doctrine import NoDoctrine
from bugflow.method.infrastructure.policy_deployment_parsing import (
    parse_deployment,
)
from bugflow.method.infrastructure.reviewer_packages import (
    DomainSpecificReviewAgent,
    installed,
)


@dataclass(frozen=True, kw_only=True)
class ReviewersInForce:
    """Everything a program derives from the deployment in force."""

    #: The reviewers, by id, after ``names`` has narrowed them.
    agents: Mapping[str, DomainSpecificReviewAgent]
    #: Each reviewer's parsed policies, by reviewer id then policy id.
    policies: Mapping[str, Mapping[str, PolicyText]]
    #: By reviewer id: the text a judge's fingerprint hashes for that
    #: reviewer's policies.
    policy_sources: Mapping[str, str]
    #: By reviewer id: the text that reviewer's corpus version hashes.
    prose: Mapping[str, str]
    #: By reviewer id, for a reviewer that has doctrine files.
    doctrine: Mapping[str, Doctrine]
    layers: Mapping[str, PaceLayer]
    #: Which deployment the reviewers were built from.
    deployed_from: DeployedFrom

    def doctrine_of(self, agent_id: str) -> DoctrineRepository:
        """Return the doctrine that reviewer cites, or an empty one
        for a reviewer with no doctrine files."""
        held = self.doctrine.get(agent_id)
        return FixedDoctrine(held) if held is not None else NoDoctrine()


def deployed_reviewers(
    deployment: PolicyDeployment,
    checks: Collection[str],
    names: Iterable[str] = (),
) -> ReviewersInForce:
    """Return the reviewers a deployment holds, parsed with ``checks``,
    the checks this server has. ``names`` narrows them to the reviewers
    named, or none to mean every reviewer.

    Raises ``PolicyDeploymentError`` if the deployment does not parse,
    and ``ReviewAgentError`` if ``names`` names a reviewer the
    deployment does not hold.
    """
    parsed = parse_deployment(deployment, checks)
    agents = installed(names, parsed.agents)
    return ReviewersInForce(
        agents=agents,
        policies={agent_id: parsed.policies[agent_id] for agent_id in agents},
        policy_sources={
            agent_id: parsed.policy_sources[agent_id] for agent_id in agents
        },
        prose={agent_id: parsed.prose[agent_id] for agent_id in agents},
        doctrine={
            agent_id: parsed.doctrine[agent_id]
            for agent_id in agents
            if agent_id in parsed.doctrine
        },
        layers=parsed.layers,
        deployed_from=DeployedFrom(
            repository=deployment.repository,
            commit=deployment.commit,
            content_hash=deployment.content_hash,
        ),
    )


def reviewers_in_force(
    deployments: PolicyDeploymentRepository,
    checks: Collection[str],
    names: Iterable[str] = (),
) -> ReviewersInForce | None:
    """Return the reviewers of the deployment in force, or None on a
    server that was never sent one, which reviews nothing.

    Reads the database once. A deployment put in force later is not
    seen; ``deployment_watch`` stops a program when that happens.
    """
    deployment = deployments.in_force()
    if deployment is None:
        return None
    return deployed_reviewers(deployment, checks, names)
