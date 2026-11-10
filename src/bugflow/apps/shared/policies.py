"""The reviewers a program runs with, from the policy deployment in
force.

A program needs the same things whichever deployment they come from: the
reviewers, each reviewer's policies and doctrine, the pace layers, the
glossary files, the editor, and the texts that feed a corpus version.
``ReviewersInForce`` holds them, and ``reviewers_in_force`` builds one
from the deployment the database says is in force for one tenant,
parsed with the checks this server has. A program that serves every
tenant, as the ingress and the API do, reads ``tenants_in_force``
(ADR 011).
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field

from bugflow.method.domain.models.doctrine import Doctrine
from bugflow.method.domain.models.editor import Editor
from bugflow.method.domain.models.pace_layer import PaceLayer
from bugflow.method.domain.models.policy_deployment import (
    DEFAULT_TENANT,
    PolicyDeployment,
)
from bugflow.method.domain.models.policy_text import (
    JUDGED_SUBJECTS,
    PolicyText,
)
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
    #: The text of each file under glossary/, by path, in path order.
    glossary: Mapping[str, str] = field(default_factory=dict)
    #: Each reviewer's profiles, by reviewer id then profile name: the
    #: policies a repository set to that profile is judged on (ADR 008).
    profiles: Mapping[str, Mapping[str, tuple[str, ...]]] = field(
        default_factory=dict
    )
    #: The binding's editor, which writes each review comment from the
    #: server's draft; None for a binding without one.
    editor: Editor | None = None
    #: Every reviewer the deployment holds, by id, before ``names``
    #: narrowed them: the gnomes whose settings are this tenant's.
    held: frozenset[str] = frozenset()

    @property
    def tenant(self) -> str:
        """Whose deployment the reviewers were built from."""
        return self.deployed_from.tenant

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
    # The subjects this server renders, so that a reviewer's default
    # profile leaves out what it cannot judge, as the deployment's own
    # check did when it was put in force.
    parsed = parse_deployment(deployment, checks, JUDGED_SUBJECTS)
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
        glossary=parsed.glossary,
        profiles={agent_id: parsed.profiles[agent_id] for agent_id in agents},
        editor=parsed.editor,
        deployed_from=DeployedFrom(
            repository=deployment.repository,
            commit=deployment.commit,
            content_hash=deployment.content_hash,
            tenant=deployment.tenant,
        ),
        held=frozenset(parsed.agents),
    )


def reviewers_in_force(
    deployments: PolicyDeploymentRepository,
    checks: Collection[str],
    names: Iterable[str] = (),
    tenant: str = DEFAULT_TENANT,
) -> ReviewersInForce | None:
    """Return the reviewers of the tenant's deployment in force, or None
    for a tenant that was never sent one, which reviews nothing.

    Reads the database once. A deployment put in force later is not
    seen; ``deployment_watch`` stops a program when that happens.
    """
    deployment = deployments.in_force(tenant)
    if deployment is None:
        return None
    return deployed_reviewers(deployment, checks, names)


@dataclass(frozen=True)
class TenantsInForce:
    """Every tenant's reviewers, for a program that serves them all.

    A reviewer's id is one tenant's on a server, which deploying holds
    to, so the gnomes of every tenant read together as one mapping.
    """

    #: By tenant, in name order.
    by_tenant: Mapping[str, ReviewersInForce]

    @property
    def tenant_of(self) -> dict[str, str]:
        """Each gnome's tenant, by the gnome's id."""
        return {
            gnome: tenant
            for tenant, reviewers in self.by_tenant.items()
            for gnome in reviewers.held
        }

    @property
    def agents(self) -> dict[str, DomainSpecificReviewAgent]:
        return {
            gnome: agent
            for reviewers in self.by_tenant.values()
            for gnome, agent in reviewers.agents.items()
        }

    @property
    def policies(self) -> dict[str, Mapping[str, PolicyText]]:
        return {
            gnome: held
            for reviewers in self.by_tenant.values()
            for gnome, held in reviewers.policies.items()
        }

    @property
    def profiles(self) -> dict[str, Mapping[str, tuple[str, ...]]]:
        """Each gnome's profiles, by gnome, across every tenant."""
        return {
            gnome: named
            for reviewers in self.by_tenant.values()
            for gnome, named in reviewers.profiles.items()
        }

    @property
    def layers(self) -> dict[str, PaceLayer]:
        """Every tenant's layers by name. Deploying holds a layer's name
        to one cadence across the server, so the one kept where two
        tenants name a layer alike rides the same clock as the other."""
        found: dict[str, PaceLayer] = {}
        for reviewers in self.by_tenant.values():
            for name, layer in reviewers.layers.items():
                found.setdefault(name, layer)
        return found

    def layers_of(self, gnome: str) -> Mapping[str, PaceLayer]:
        """The layers of the tenant whose gnome that is, or none for a
        gnome no tenant holds."""
        tenant = self.tenant_of.get(gnome)
        return self.by_tenant[tenant].layers if tenant else {}

    @property
    def deployed(self) -> dict[str, DeployedFrom]:
        """Which deployment each tenant's reviewers were built from."""
        return {
            tenant: reviewers.deployed_from
            for tenant, reviewers in self.by_tenant.items()
        }


def tenants_in_force(
    deployments: PolicyDeploymentRepository, checks: Collection[str]
) -> TenantsInForce:
    """Return every tenant's reviewers, from each tenant's deployment in
    force. A server never sent one holds no tenant."""
    found: dict[str, ReviewersInForce] = {}
    for tenant in deployments.tenants():
        reviewers = reviewers_in_force(deployments, checks, tenant=tenant)
        if reviewers is not None:
            found[tenant] = reviewers
    return TenantsInForce(by_tenant=found)
