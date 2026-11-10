"""Deploying policies, composed: the use case that stores a deployment
and puts it in force, with a check that reads the settings as well as
the files.

The use case is the method context's and the gnomes' settings are the
review context's, so the two are joined here, where both may be
imported. A deployment that drops a profile, or a gnome, that a setting
above ``off`` names is refused (ADR 008), so a repository is never left
judged by a profile that is gone. A setting switched off holds nothing
in place: a gnome switched off everywhere may leave the binding, and
one switched on again whose profile is gone is given ``default``.
Refused too is a deployment that gives a layer a cadence a declared
boundary on it cannot take, which the ingress or the worker would raise
on. On a server with several tenants (ADR 011), so is one that names a
layer another tenant's deployment in force holds at a different
cadence: a layer's cadence is one across the server, because a boundary
is declared on the layer's name with no tenant. A reviewer's id is not
one tenant's: a setting names its tenant (ADR 012), so two tenants may
hold a reviewer of one id. The API's route and the command's
``install-policies`` run the same composition, so a deployment made on
the host is checked and recorded as one a pipeline sends is.
"""

import sys
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from bugflow.apps.shared.journals import stamped_journal
from bugflow.method.domain.errors import (
    PolicyDeploymentConflictError,
    PolicyDeploymentError,
)
from bugflow.method.domain.models.boundary import BoundaryError
from bugflow.method.domain.models.pace_layer import PaceLayer, check_boundary
from bugflow.method.domain.models.policy_deployment import (
    DEFAULT_TENANT,
    PolicyDeployment,
)
from bugflow.method.domain.models.policy_text import JUDGED_SUBJECTS
from bugflow.method.domain.repositories.policy_deployment import (
    PolicyDeploymentRepository,
)
from bugflow.method.dtos.deploy_policies import (
    DeployPoliciesRequest,
    PolicyFile,
)
from bugflow.method.infrastructure.policy_deployment_parsing import (
    ParsedDeployment,
    parse_deployment,
    refuse_retired,
)
from bugflow.method.infrastructure.policy_directory import PolicyDirectory
from bugflow.method.infrastructure.sqlalchemy_policy_deployments import (
    SqlAlchemyPolicyDeployments,
)
from bugflow.method.usecases.deploy_policies import DeployPoliciesUseCase
from bugflow.review.domain.services.gnome_settings import (
    GnomeSettingsService,
)
from bugflow.review.domain.services.layer_boundaries import (
    LayerBoundariesService,
)
from bugflow.review.domain.values.checked_policy import CHECKS
from bugflow.review.infrastructure.sqlalchemy_gnome_settings import (
    SqlAlchemyGnomeSettings,
)
from bugflow.review.infrastructure.sqlalchemy_layer_boundaries import (
    SqlAlchemyLayerBoundaries,
)
from bugflow.shared.infrastructure.system_clock import SystemClock

#: The setting that names the checks this server performs, comma-
#: separated. Unset, the server performs none, and a manifest naming
#: one is refused.
CHECKS_VARIABLE = "POLICY_CHECKS"


def checks_from(environ: Mapping[str, str]) -> tuple[str, ...]:
    """Return the names of the checks this server performs: the ones the
    package has, unless ``POLICY_CHECKS`` lists them."""
    if CHECKS_VARIABLE not in environ:
        return CHECKS
    return tuple(
        name.strip()
        for name in environ[CHECKS_VARIABLE].split(",")
        if name.strip()
    )


class SettledDeploymentCheck:
    """Implements ``PolicyDeploymentCheckService``: a retired file is
    refused, then the parse, told which checks this server has and which
    subjects it renders, then the cadence the other tenants' deployments
    in force give each layer, which this one may not give otherwise,
    then each declared boundary, which the cadence the deployment gives
    its layer must take, and then each of this tenant's settings, which
    must name a gnome and a profile the deployment holds."""

    def __init__(
        self,
        checks: Collection[str],
        settings: GnomeSettingsService | None = None,
        boundaries: LayerBoundariesService | None = None,
        deployments: PolicyDeploymentRepository | None = None,
    ) -> None:
        self._checks = checks
        self._settings = settings
        self._boundaries = boundaries
        self._deployments = deployments

    def _their_layers(self, tenant: str) -> dict[str, tuple[str, PaceLayer]]:
        """The layers the other tenants' deployments in force hold: each
        layer's tenant and layer, by layer name."""
        layers: dict[str, tuple[str, PaceLayer]] = {}
        if self._deployments is None:
            return layers
        for other in self._deployments.tenants():
            if other == tenant:
                continue
            held = self._deployments.in_force(other)
            if held is None:
                continue
            try:
                theirs = parse_deployment(held, self._checks, JUDGED_SUBJECTS)
            except PolicyDeploymentError as exc:
                raise PolicyDeploymentError(
                    f"the deployment in force for {other} does not parse, "
                    f"so what it holds cannot be kept apart from this one: "
                    f"{exc}"
                ) from exc
            for name, layer in theirs.layers.items():
                layers.setdefault(name, (other, layer))
        return layers

    def _refuse_a_layer_another_tenant_runs_otherwise(
        self,
        parsed: ParsedDeployment,
        layers: Mapping[str, tuple[str, PaceLayer]],
    ) -> None:
        crossed = sorted(
            f"{name} runs at the {theirs[1].cadence.name} cadence for "
            f"{other} and at the {layer.cadence.name} cadence here"
            for name, layer in parsed.layers.items()
            if (theirs := layers.get(name)) is not None
            and theirs[1].cadence.name != layer.cadence.name
            for other in (theirs[0],)
        )
        if crossed:
            raise PolicyDeploymentError(
                "the deployment gives a layer a cadence another tenant's "
                "deployment in force gives it otherwise: "
                + "; ".join(crossed)
                + ". A layer's name has one cadence on a server, since a "
                "boundary is declared on the name"
            )

    def check(self, deployment: PolicyDeployment) -> None:
        refuse_retired(deployment)
        parsed = parse_deployment(deployment, self._checks, JUDGED_SUBJECTS)
        self._refuse_a_layer_another_tenant_runs_otherwise(
            parsed, self._their_layers(deployment.tenant)
        )
        if self._boundaries is not None:
            unfit = []
            for one in self._boundaries.declarations():
                layer = parsed.layers.get(one.layer)
                if layer is None:
                    continue
                try:
                    check_boundary(layer.cadence, one.boundary)
                except BoundaryError:
                    unfit.append(
                        f"{one.forge}:{one.repo} begins {one.layer} at "
                        f"{one.boundary!r}, which the "
                        f"{layer.cadence.name} cadence cannot take"
                    )
            if unfit:
                raise PolicyDeploymentError(
                    "the deployment gives a layer a cadence a declared "
                    "boundary cannot take: "
                    + "; ".join(sorted(unfit))
                    + ". Declare those boundaries again, or withdraw "
                    "them, first"
                )
        if self._settings is None:
            return
        # Another tenant's setting is that tenant's deployment to keep,
        # and a setting switched off judges by nothing.
        dropped = sorted(
            f"{one.forge}:{one.repo} sets {one.gnome} to {one.profile}"
            for one in self._settings.settings()
            if one.tenant == deployment.tenant
            and one.behaviour != "off"
            and one.profile not in parsed.profiles.get(one.gnome, {})
        )
        if dropped:
            raise PolicyDeploymentError(
                "the deployment drops a profile a setting names: "
                + "; ".join(dropped)
                + ". Set those gnomes to another profile, or off, first"
            )


def deployment_check(
    checks: Collection[str],
    settings: GnomeSettingsService | None = None,
    boundaries: LayerBoundariesService | None = None,
    deployments: PolicyDeploymentRepository | None = None,
) -> SettledDeploymentCheck:
    """Return the check a deployment passes before it is stored.
    ``deployments`` is where the other tenants' deployments in force are
    read from; given none, nothing is kept apart from them."""
    return SettledDeploymentCheck(checks, settings, boundaries, deployments)


@dataclass(frozen=True)
class Deploying:
    """What deploys: the use case, and where deployments are kept, which
    answers what is in force."""

    deploy: DeployPoliciesUseCase
    deployments: PolicyDeploymentRepository


def deploying_with(
    deployments: PolicyDeploymentRepository,
    checks: Collection[str],
    settings: GnomeSettingsService | None = None,
    boundaries: LayerBoundariesService | None = None,
) -> Deploying:
    """Compose deploying over the stores given. For a test, or a program
    that holds the stores already. ``deployments`` records the facts of
    a deployment, so it is given the journal."""
    return Deploying(
        deploy=DeployPoliciesUseCase(
            deployments,
            deployment_check(checks, settings, boundaries, deployments),
            SystemClock(),
        ),
        deployments=deployments,
    )


def deploying_over(
    database_url: str, build: str | None, checks: Collection[str]
) -> Deploying:
    """Compose deploying over the Postgres stores, the journal stamped
    with ``build``."""
    return deploying_with(
        SqlAlchemyPolicyDeployments(
            database_url, stamped_journal(database_url, build)
        ),
        checks,
        SqlAlchemyGnomeSettings(database_url),
        SqlAlchemyLayerBoundaries(database_url),
    )


#: What the fact records as the sender of a deployment made on the host.
INSTALLED_ON_THE_HOST = "bugflow install-policies on the host"


def run_install_policies(
    directory: Path,
    repository: str,
    commit: str,
    deploying: Deploying,
    checks: Collection[str],
    out: TextIO | None = None,
    check_only: bool = False,
    tenant: str = DEFAULT_TENANT,
) -> int:
    """Store what the directory holds and put it in force for the
    tenant; 0 when the database holds it afterwards. With
    ``check_only``, parse it and store nothing; 0 when it parses.

    Prints what the database holds afterwards, read back and not
    echoed.
    """
    out = out or sys.stdout
    if not directory.is_dir():
        print(f"error: {directory} is not a directory", file=sys.stderr)
        return 2
    read = PolicyDirectory(directory).read(repository, commit)
    try:
        answered = deploying.deploy.execute(
            DeployPoliciesRequest(
                repository=repository,
                commit=commit,
                files=tuple(
                    PolicyFile(path=one.path, text=one.text)
                    for one in read.files
                ),
                sent_by=INSTALLED_ON_THE_HOST,
                check_only=check_only,
                tenant=tenant,
            )
        )
    except (PolicyDeploymentError, PolicyDeploymentConflictError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if check_only:
        print(
            f"checked {len(read.files)} files, content "
            f"{answered.content_hash[:12]}; nothing stored",
            file=out,
        )
        return 0
    now = deploying.deployments.in_force(tenant)
    if now is None:
        print("error: nothing is in force after the write", file=sys.stderr)
        return 1
    whose = "" if tenant == DEFAULT_TENANT else f" for {tenant}"
    print(
        f"{now.repository} at {now.commit} is in force{whose}, "
        f"{len(now.files)} files, content {now.content_hash[:12]}"
        + ("" if answered.outcome == "deployed" else "; it already was"),
        file=out,
    )
    for one in now.files:
        print(f"  {one.path}", file=out)
    return 0
