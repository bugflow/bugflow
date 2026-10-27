"""Use case: set what one gnome does on one repository (ADR 008).

This is the only way a setting changes. Every change is written to the
journal as ``gnome.set``, with who made it and what it replaced, before
the setting is saved, so a setting never stands without its record.
"""

from bugflow.review.domain.facts import GNOME_SET, gnome_set_id
from bugflow.review.domain.models.gnome_setting import GnomeSetting
from bugflow.review.domain.services.gnome_settings import (
    GnomeSettingsService,
)
from bugflow.review.dtos.set_gnome import SetGnomeRequest, SetGnomeResponse
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService

# A journal entry names the workflow that recorded it. A setting comes
# from an operator and not from a workflow, so its entries use this
# fixed name in that place.
WORKFLOW_ID = "gnome/set"


class UnknownGnomeError(ValueError):
    """A setting names a gnome or a profile the deployment in force does
    not hold."""


class SetGnomeUseCase:
    """Takes a repository, a gnome, a behaviour and a profile. Returns
    whether anything changed and what it replaced."""

    def __init__(
        self,
        settings: GnomeSettingsService,
        journal: RecordingService,
        clock: ClockService,
        run_id: str,
    ) -> None:
        self._settings = settings
        self._journal = journal
        self._clock = clock
        self._run_id = run_id

    def execute(self, request: SetGnomeRequest) -> SetGnomeResponse:
        """Raises ``UnknownGnomeError`` for a gnome or profile the
        deployment in force does not hold, unless the gnome is switched
        off, and ``ValueError`` for a setting that is not one."""
        held = request.profiles.get(request.gnome)
        if request.behaviour == "off":
            # A gnome may always be switched off, even one the
            # deployment in force no longer holds.
            pass
        elif held is None:
            known = ", ".join(sorted(request.profiles)) or "none"
            raise UnknownGnomeError(
                f"{request.gnome!r} is not a gnome the deployment in force "
                f"holds; it holds {known}"
            )
        elif request.profile not in held:
            raise UnknownGnomeError(
                f"{request.profile!r} is not a profile of {request.gnome}; "
                f"it has {', '.join(held)}"
            )
        when = self._clock.now()
        setting = GnomeSetting(
            forge=request.forge,
            repo=request.repo,
            gnome=request.gnome,
            behaviour=request.behaviour,
            profile=request.profile,
            set_by=request.set_by,
            set_at=when,
        )
        previous = next(
            (
                one
                for one in self._settings.settings_of(
                    request.forge, request.repo
                )
                if one.gnome == request.gnome
            ),
            None,
        )
        changed = previous is None or (
            previous.behaviour,
            previous.profile,
        ) != (setting.behaviour, setting.profile)
        if changed:
            self._journal.append([self._entry(setting, previous)])
            self._settings.save(setting)
        return SetGnomeResponse(
            forge=setting.forge,
            repo=setting.repo,
            gnome=setting.gnome,
            behaviour=setting.behaviour,
            profile=setting.profile,
            changed=changed,
            was_behaviour=previous.behaviour if previous else None,
            was_profile=previous.profile if previous else None,
        )

    def _entry(
        self, setting: GnomeSetting, previous: GnomeSetting | None
    ) -> JournalEntry:
        assert setting.set_at is not None
        return JournalEntry(
            event_id=gnome_set_id(
                setting.forge,
                setting.repo,
                setting.gnome,
                (setting.behaviour, setting.profile),
                (previous.behaviour, previous.profile) if previous else None,
                setting.set_at,
            ),
            occurred_at=setting.set_at,
            event_type=GNOME_SET,
            forge=setting.forge,
            repo=setting.repo,
            pr_number=None,
            commit_sha=None,
            corpus_version=None,
            workflow_id=WORKFLOW_ID,
            run_id=self._run_id,
            agent_id=setting.gnome,
            payload={
                "behaviour": setting.behaviour,
                "profile": setting.profile,
                "set_by": setting.set_by,
                "was_behaviour": previous.behaviour if previous else None,
                "was_profile": previous.profile if previous else None,
            },
        )
