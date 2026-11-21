"""Use case: move a renamed repository's settings and declarations to
its new name (ADR 008).

A forge keeps a renamed repository's pull requests, so the gnomes set
on its old name should judge it under the new, and its periods and
withheld share should go with it. Each gnome set on the old name, other
than off, is set the same on the new name, unless the new name already
has a setting for that gnome, which is kept. Each is then switched off
on the old name, so the old name is no longer watched. Every change of
a setting goes through ``SetGnomeUseCase``, so it is recorded in the
journal as any other setting is.

A setting is copied as it stands, profile and all, without asking the
deployment in force whether it still holds the gnome: the setting was
accepted once, and moving it changes only the name it is set on.

The old name's boundary on each layer, and its withheld share, are
declared on the new name where the new name has declared none, each
recorded as ``bugflow declare`` records one. Without its boundary, a
repository watched on a layer stops the worker at its next start. The
old name keeps its own, since it is no longer watched.

Allowances are not moved: an allowance may name an owner, which a rename
under the owner does not change. Archive ledgers are the archive's, and
``MoveLedgersUseCase`` moves them.
"""

import json
from collections.abc import Mapping

from bugflow.review.domain.facts import (
    BOUNDARY_DECLARED,
    WITHHOLDING_DECLARED,
    declaration_id,
)
from bugflow.review.domain.models.gnome_setting import qualified
from bugflow.review.domain.models.layer_boundary import LayerBoundary
from bugflow.review.domain.models.withholding import Withholding
from bugflow.review.domain.services.gnome_settings import (
    GnomeSettingsService,
)
from bugflow.review.domain.services.layer_boundaries import (
    LayerBoundariesService,
)
from bugflow.review.domain.services.withholding import WithholdingService
from bugflow.review.dtos.move_repository_settings import (
    MoveRepositorySettingsRequest,
    MoveRepositorySettingsResponse,
)
from bugflow.review.dtos.set_gnome import SetGnomeRequest
from bugflow.review.usecases.set_gnome import SetGnomeUseCase
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService

#: The workflow a moved declaration's fact names, where an operator's
#: names ``operator/declare``.
WORKFLOW_ID = "repository/moved"


class MoveRepositorySettingsUseCase:
    """Takes a repository's old and new names. Returns what was moved,
    and which gnomes the new name already had."""

    def __init__(
        self,
        settings: GnomeSettingsService,
        setter: SetGnomeUseCase,
        boundaries: LayerBoundariesService,
        withholding: WithholdingService,
        journal: RecordingService,
        clock: ClockService,
        run_id: str,
    ) -> None:
        self._settings = settings
        self._setter = setter
        self._boundaries = boundaries
        self._withholding = withholding
        self._journal = journal
        self._clock = clock
        self._run_id = run_id

    def execute(
        self, request: MoveRepositorySettingsRequest
    ) -> MoveRepositorySettingsResponse:
        boundaries = self._move_boundaries(request)
        withholding = self._move_withholding(request)
        moved, kept = self._move_gnomes(request)
        return MoveRepositorySettingsResponse(
            moved=moved,
            kept=kept,
            boundaries=boundaries,
            withholding=withholding,
        )

    def _move_gnomes(
        self, request: MoveRepositorySettingsRequest
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        there = {
            (one.gnome, one.tenant)
            for one in self._settings.settings_of(request.forge, request.to)
        }
        moved: list[str] = []
        kept: list[str] = []
        for one in self._settings.settings_of(request.forge, request.repo):
            if one.behaviour == "off":
                continue
            name = qualified(one.tenant, one.gnome)
            profiles = {one.gnome: (one.profile,)}
            if (one.gnome, one.tenant) in there:
                kept.append(name)
            else:
                self._setter.execute(
                    SetGnomeRequest(
                        forge=request.forge,
                        repo=request.to,
                        gnome=one.gnome,
                        behaviour=one.behaviour,
                        profile=one.profile,
                        tenant=one.tenant,
                        set_by=request.set_by,
                        profiles=profiles,
                    )
                )
                moved.append(name)
            self._setter.execute(
                SetGnomeRequest(
                    forge=request.forge,
                    repo=request.repo,
                    gnome=one.gnome,
                    behaviour="off",
                    profile=one.profile,
                    tenant=one.tenant,
                    set_by=request.set_by,
                    profiles=profiles,
                )
            )
        return tuple(moved), tuple(kept)

    def _move_boundaries(
        self, request: MoveRepositorySettingsRequest
    ) -> tuple[str, ...]:
        held = self._boundaries.declarations()
        there = {
            one.layer
            for one in held
            if (one.forge, one.repo) == (request.forge, request.to)
        }
        moved: list[str] = []
        for one in held:
            if (one.forge, one.repo) != (request.forge, request.repo):
                continue
            if one.layer in there:
                continue
            self._record(
                BOUNDARY_DECLARED,
                request,
                {"layer": one.layer, "boundary": one.boundary, "was": None},
            )
            self._boundaries.declare(
                LayerBoundary(
                    forge=request.forge,
                    repo=request.to,
                    layer=one.layer,
                    boundary=one.boundary,
                )
            )
            moved.append(one.layer)
        return tuple(moved)

    def _move_withholding(
        self, request: MoveRepositorySettingsRequest
    ) -> bool:
        held = {
            one.repo: one.share
            for one in self._withholding.declarations()
            if one.forge == request.forge
        }
        if request.repo not in held or request.to in held:
            return False
        share = held[request.repo]
        self._record(
            WITHHOLDING_DECLARED, request, {"share": share, "was": 0.0}
        )
        self._withholding.declare(
            Withholding(forge=request.forge, repo=request.to, share=share)
        )
        return True

    def _record(
        self,
        event_type: str,
        request: MoveRepositorySettingsRequest,
        payload: Mapping[str, object],
    ) -> None:
        when = self._clock.now()
        said = {**payload, "declared_by": request.set_by, "from": request.repo}
        self._journal.append(
            [
                JournalEntry(
                    event_id=declaration_id(
                        event_type,
                        request.forge,
                        request.to,
                        json.dumps(said, sort_keys=True),
                        when=when,
                    ),
                    occurred_at=when,
                    event_type=event_type,
                    forge=request.forge,
                    repo=request.to,
                    pr_number=None,
                    commit_sha=None,
                    corpus_version=None,
                    workflow_id=WORKFLOW_ID,
                    run_id=self._run_id,
                    agent_id=None,
                    payload=said,
                )
            ]
        )
