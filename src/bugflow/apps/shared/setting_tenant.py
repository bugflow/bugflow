"""Whose a setting is, when the operator names no tenant (ADR 012).

A setting names its gnome's tenant. The settings page knows it, and
sends it. An operator at ``bugflow set`` need not, on a server where
the gnome's id is one tenant's: the tenant is the one whose deployment
in force holds the gnome, or, for a gnome no deployment holds any more,
the one whose setting of it the repository has, which is what switching
such a gnome off is for. A server with one tenant never names one.
Where two tenants hold the gnome, the operator names one.
"""

from collections.abc import Iterable

from bugflow.apps.shared.policies import TenantsInForce
from bugflow.method.domain.errors import PolicyDeploymentError
from bugflow.method.domain.models.policy_deployment import (
    DEFAULT_TENANT,
    checked_tenant,
)
from bugflow.review.domain.models.gnome_setting import GnomeSetting


def tenant_of_setting(
    reviewers: TenantsInForce,
    gnome: str,
    kept: Iterable[GnomeSetting],
    named: str | None = None,
) -> str:
    """The tenant a setting of ``gnome`` is: ``named`` where the
    operator named one, else the one tenant that holds the gnome, in
    force or in ``kept``, the repository's settings, else ``default``.

    Raises ``ValueError`` for a name that is no tenant's, and where two
    tenants hold the gnome and none is named.
    """
    if named is not None:
        try:
            return checked_tenant(named)
        except PolicyDeploymentError as exc:
            raise ValueError(str(exc)) from exc
    holding = reviewers.tenants_of(gnome) or tuple(
        sorted({one.tenant for one in kept if one.gnome == gnome})
    )
    if len(holding) > 1:
        raise ValueError(
            f"{gnome} is held by {' and '.join(holding)}; name the tenant "
            "whose setting this is"
        )
    return holding[0] if holding else DEFAULT_TENANT
