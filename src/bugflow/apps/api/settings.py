"""The routes and the page that set each gnome on each repository
(ADR 008).

``GET /api/settings`` lists every repository the server knows of, from
its journal and from discovery, with what each gnome is set to there,
and each gnome's profiles. ``PUT /api/settings/{forge}/{owner}/{repo}/
{gnome}`` sets one gnome on one repository, recorded as set by the
caller. Both need the role ``SETTINGS_ROLE`` names.

``GET /settings`` is the page, which signs the person in at the identity
provider in the browser and calls the two routes with the token it is
given. ``GET /settings/config`` tells the page where to sign in. Neither
needs a token: the page holds no data until the routes give it some.
"""

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from importlib.resources import files
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict

from bugflow.apps.shared.boundaries import Defaulted, without_a_boundary
from bugflow.apps.shared.policies import ReviewersInForce
from bugflow.forge.domain.models.forge_repository import KnownRepository
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.review.domain.models.gnome_setting import (
    DEFAULT_PROFILE,
    Behaviour,
    GnomeSetting,
)
from bugflow.review.domain.services.gnome_settings import (
    GnomeSettingsService,
)
from bugflow.review.domain.services.layer_boundaries import (
    LayerBoundariesService,
)
from bugflow.review.dtos.set_gnome import SetGnomeRequest
from bugflow.review.usecases.set_gnome import (
    SetGnomeUseCase,
    UnknownGnomeError,
)
from bugflow.shared.domain.values.caller import Caller

#: The page, kept beside this module.
PAGE = "settings_page.html"


@dataclass(frozen=True)
class PageSignIn:
    """Where the page signs a person in: the identity provider, the
    public client the page is registered as, and the scopes it asks for,
    which must give a token the API accepts."""

    issuer: str
    client_id: str
    scope: str = "openid profile"


@dataclass(frozen=True)
class SettingsAdministration:
    """What the settings routes are served with."""

    #: The role a caller needs to read or change a setting.
    role: str
    settings: GnomeSettingsService
    set_gnome: Callable[[], SetGnomeUseCase]
    #: Every repository this server knows of.
    repositories: Callable[[], Collection[KnownRepository]]
    #: The reviewers of the deployment in force, or None.
    reviewers: Callable[[], ReviewersInForce | None]
    boundaries: LayerBoundariesService
    sign_in: PageSignIn | None = None


class GnomeState(BaseModel):
    model_config = ConfigDict(frozen=True)

    behaviour: Behaviour
    profile: str
    set_by: str
    set_at: str | None


class RepositoryState(BaseModel):
    model_config = ConfigDict(frozen=True)

    forge: str
    name: str
    archived: bool
    #: By gnome. A gnome missing is off and was never set here.
    gnomes: dict[str, GnomeState]


class SettingsState(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: Each gnome's profiles, by gnome.
    profiles: dict[str, list[str]]
    repositories: list[RepositoryState]


class SetGnomeBody(BaseModel):
    model_config = ConfigDict(frozen=True)

    behaviour: Behaviour
    #: Omitted, the gnome keeps its profile there, or ``default``.
    profile: str | None = None


def _state(
    one: KnownRepository, settings: Collection[GnomeSetting]
) -> RepositoryState:
    return RepositoryState(
        forge=one.forge,
        name=one.name,
        archived=one.archived,
        gnomes={
            held.gnome: GnomeState(
                behaviour=held.behaviour,
                profile=held.profile,
                set_by=held.set_by,
                set_at=held.set_at.isoformat() if held.set_at else None,
            )
            for held in settings
            if (held.forge, held.repo) == (one.forge, one.name)
        },
    )


def _profiles(
    reviewers: ReviewersInForce | None,
) -> dict[str, list[str]]:
    if reviewers is None:
        return {}
    return {
        gnome: sorted(named, key=lambda name: (name != DEFAULT_PROFILE, name))
        for gnome, named in sorted(reviewers.profiles.items())
    }


def settings_routes(
    app: FastAPI,
    caller: Callable[..., Caller],
    admin: SettingsAdministration,
) -> None:
    """Add the settings routes and the page to ``app``."""

    def administrator(who: Annotated[Caller, Depends(caller)]) -> Caller:
        if admin.role not in who.roles:
            raise HTTPException(
                403, "this caller may not read or change the settings"
            )
        return who

    @app.get("/api/settings")
    def read_settings(
        who: Annotated[Caller, Depends(administrator)],
    ) -> SettingsState:
        held = admin.settings.settings()
        known = {(one.forge, one.name): one for one in admin.repositories()}
        for one in held:
            known.setdefault(
                (one.forge, one.repo),
                KnownRepository(forge=one.forge, name=one.repo),
            )
        return SettingsState(
            profiles=_profiles(admin.reviewers()),
            repositories=[_state(known[key], held) for key in sorted(known)],
        )

    @app.put("/api/settings/{forge}/{owner}/{repo}/{gnome}")
    def set_gnome(
        forge: str,
        owner: str,
        repo: str,
        gnome: str,
        body: SetGnomeBody,
        who: Annotated[Caller, Depends(administrator)],
    ) -> RepositoryState:
        name = f"{owner}/{repo}"
        try:
            if forge not in ("github", "forgejo"):
                raise ValueError(forge)
            WatchedRepository.parse(f"{forge}:{name}")
        except ValueError as exc:
            raise HTTPException(
                422, f"{forge}:{name} is not a repository this server reads"
            ) from exc
        reviewers = admin.reviewers()
        if reviewers is None and body.behaviour != "off":
            raise HTTPException(
                409, "no policy deployment is in force, so no gnome can judge"
            )
        if body.behaviour != "off" and reviewers is not None:
            watched = f"{forge}:{name}" if forge != "github" else name
            missing = without_a_boundary(
                reviewers.layers,
                [watched],
                Defaulted(admin.boundaries, reviewers.layers),
            )
            if missing:
                raise HTTPException(
                    409,
                    f"{name} has no boundary on {', '.join(missing)}, and "
                    "the layer gives no default; a worker watching it "
                    "would not start. Declare one with bugflow declare, "
                    "or give the layer a default_boundary",
                )
        kept = next(
            (
                one
                for one in admin.settings.settings_of(forge, name)
                if one.gnome == gnome
            ),
            None,
        )
        offered = _profiles(reviewers)
        profile = body.profile or (kept.profile if kept else DEFAULT_PROFILE)
        if body.profile is None and profile not in offered.get(gnome, []):
            # The profile it was set to is gone, and the page offers no
            # choice where a gnome has one profile.
            profile = DEFAULT_PROFILE
        try:
            admin.set_gnome().execute(
                SetGnomeRequest(
                    forge=forge,
                    repo=name,
                    gnome=gnome,
                    behaviour=body.behaviour,
                    profile=profile,
                    set_by=who.subject,
                    profiles={
                        one: tuple(named) for one, named in offered.items()
                    },
                )
            )
        except (UnknownGnomeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        known = next(
            (
                one
                for one in admin.repositories()
                if (one.forge, one.name) == (forge, name)
            ),
            KnownRepository(forge=forge, name=name),
        )
        return _state(known, admin.settings.settings_of(forge, name))

    @app.get("/settings/config")
    def page_config() -> dict[str, Any]:
        """Where the page signs a person in, or 404 where it does not."""
        if admin.sign_in is None:
            raise HTTPException(404, "the settings page is not set up")
        return {
            "issuer": admin.sign_in.issuer,
            "client_id": admin.sign_in.client_id,
            "scope": admin.sign_in.scope,
        }

    @app.get("/settings", response_class=HTMLResponse)
    def page() -> str:
        return files("bugflow.apps.api").joinpath(PAGE).read_text()


def sign_in_from(environ: Mapping[str, str], issuer: str) -> PageSignIn | None:
    """Where the page signs in: ``SETTINGS_CLIENT_ID`` and
    ``SETTINGS_SCOPE``. None where no client is named."""
    client_id = environ.get("SETTINGS_CLIENT_ID", "")
    if not client_id:
        return None
    return PageSignIn(
        issuer=issuer,
        client_id=client_id,
        scope=environ.get("SETTINGS_SCOPE") or "openid profile",
    )
