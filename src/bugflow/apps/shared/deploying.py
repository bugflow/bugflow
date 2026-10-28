"""Deploying policies, composed: the use case that stores a deployment
and puts it in force, with a check that reads the settings as well as
the files.

The use case is the method context's and the gnomes' settings are the
review context's, so the two are joined here, where both may be
imported. A deployment that drops a profile, or a gnome, that a setting
names is refused (ADR 008), so a repository is never left set to a
profile that is gone, even with its gnome off. So is one that gives a
layer a cadence a declared boundary on it cannot take, which the
ingress or the worker would raise on. The API's route and the
command's ``install-policies`` run the same composition, so a
deployment made on the host is checked and recorded as one a pipeline
sends is.
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
from bugflow.method.domain.models.pace_layer import check_boundary
from bugflow.method.domain.models.policy_deployment import PolicyDeployment
from bugflow.method.domain.models.policy_text import JUDGED_SUBJECTS
from bugflow.method.domain.repositories.policy_deployment import (
    PolicyDeploymentRepository,
)
from bugflow.method.dtos.deploy_policies import (
    DeployPoliciesRequest,
    PolicyFile,
)
from bugflow.method.infrastructure.policy_deployment_parsing import (
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
from bugflow.shared.domain.services.recording import RecordingService
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
    subjects it renders, then each setting, which must name a gnome and
    a profile the deployment holds, and then each declared boundary,
    which the cadence the deployment gives its layer must take."""

    def __init__(
        self,
        checks: Collection[str],
        settings: GnomeSettingsService | None = None,
        boundaries: LayerBoundariesService | None = None,
    ) -> None:
        self._checks = checks
        self._settings = settings
        self._boundaries = boundaries

    def check(self, deployment: PolicyDeployment) -> None:
        refuse_retired(deployment)
        parsed = parse_deployment(deployment, self._checks, JUDGED_SUBJECTS)
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
        dropped = sorted(
            f"{one.forge}:{one.repo} sets {one.gnome} to {one.profile}"
            for one in self._settings.settings()
            if one.profile not in parsed.profiles.get(one.gnome, {})
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
) -> SettledDeploymentCheck:
    """Return the check a deployment passes before it is stored."""
    return SettledDeploymentCheck(checks, settings, boundaries)


@dataclass(frozen=True)
class Deploying:
    """What deploys: the use case, and where deployments are kept, which
    answers what is in force."""

    deploy: DeployPoliciesUseCase
    deployments: PolicyDeploymentRepository


def deploying_with(
    deployments: PolicyDeploymentRepository,
    recording: RecordingService,
    checks: Collection[str],
    settings: GnomeSettingsService | None = None,
    boundaries: LayerBoundariesService | None = None,
) -> Deploying:
    """Compose deploying over the stores given. For a test, or a program
    that holds the stores already."""
    return Deploying(
        deploy=DeployPoliciesUseCase(
            deployments,
            deployment_check(checks, settings, boundaries),
            recording,
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
        SqlAlchemyPolicyDeployments(database_url),
        stamped_journal(database_url, build),
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
) -> int:
    """Store what the directory holds and put it in force; 0 when the
    database holds it afterwards. With ``check_only``, parse it and
    store nothing; 0 when it parses.

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
    now = deploying.deployments.in_force()
    if now is None:
        print("error: nothing is in force after the write", file=sys.stderr)
        return 1
    print(
        f"{now.repository} at {now.commit} is in force, "
        f"{len(now.files)} files, content {now.content_hash[:12]}"
        + ("" if answered.outcome == "deployed" else "; it already was"),
        file=out,
    )
    for one in now.files:
        print(f"  {one.path}", file=out)
    return 0
