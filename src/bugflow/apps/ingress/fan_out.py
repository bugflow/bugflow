"""One starter for each tenant, and the choice of which a delivery
reaches (ADR 011).

A server has one ingress and a worker for each tenant, each in a
namespace of its own. A pull request's delivery is handed to the
workflow of each tenant whose gnome judges the repository, read from
the gnomes' settings when the delivery arrives, so a gnome set on a
repository is reached without a restart. A repository no tenant's gnome
judges is handed to the ingress's own tenant, as a server with one
tenant hands every delivery: its deliveries are journalled and judged
on nothing (ADR 008). A runner's completion is handed to the tenant
whose reviewer was dispatched.
"""

from collections.abc import Mapping
from typing import Protocol

from bugflow.forge.domain.services.evaluations import EvaluationStarterPort
from bugflow.review.domain.services.gnome_settings import (
    GnomeSettingsService,
)
from bugflow.shared.domain.values.acknowledgement import Acknowledgement
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.work.domain.services.completion_handler import CompletionHandler


class TenantStarter(EvaluationStarterPort, CompletionHandler, Protocol):
    """What one tenant's starter does: start, close and complete."""


class TenantStarters:
    """Implements the forge's ``EvaluationStarterPort`` and the work
    context's ``CompletionHandler`` over one starter for each tenant.

    ``own`` is the ingress's own tenant, which always has a starter.
    ``tenant_of`` gives each gnome's tenant, from every tenant's
    deployment in force; a gnome of a tenant with no starter reaches
    nothing, which the ingress says when it starts.
    """

    def __init__(
        self,
        starters: Mapping[str, TenantStarter],
        own: str,
        tenant_of: Mapping[str, str],
        settings: GnomeSettingsService,
    ) -> None:
        if own not in starters:
            raise ValueError(f"the own tenant {own} has no starter")
        self._starters = dict(starters)
        self._own = own
        self._tenant_of = dict(tenant_of)
        self._settings = settings

    def tenants_for(self, ref: PullRequestRef) -> tuple[str, ...]:
        """The tenants whose gnomes judge the pull request's repository
        and have a starter, in name order, or the own tenant where none
        does."""
        held = self._settings.settings_of(ref.forge, f"{ref.owner}/{ref.repo}")
        judging = {
            self._tenant_of[one.gnome]
            for one in held
            if one.judges and one.gnome in self._tenant_of
        }
        reached = tuple(sorted(judging & set(self._starters)))
        return reached or (self._own,)

    def start(self, ref: PullRequestRef, delivery_id: str) -> Correlation:
        started = [
            self._starters[tenant].start(ref, delivery_id)
            for tenant in self.tenants_for(ref)
        ]
        return started[0]

    def close(
        self, ref: PullRequestRef, delivery_id: str, merged: bool = False
    ) -> Correlation | None:
        # Every tenant's workflow for the pull request, since a gnome
        # may have been switched off while it ran.
        closed = [
            self._starters[tenant].close(ref, delivery_id, merged)
            for tenant in sorted(self._starters)
        ]
        return next((one for one in closed if one is not None), None)

    def handle_completion(
        self, correlation: Correlation, agent_id: str, remote_id: str
    ) -> Acknowledgement:
        tenant = self._tenant_of.get(agent_id, self._own)
        starter = self._starters.get(tenant, self._starters[self._own])
        return starter.handle_completion(correlation, agent_id, remote_id)
