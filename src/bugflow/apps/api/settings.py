"""The routes and the page that set each gnome on each repository
(ADR 008).

``GET /api/settings`` lists every repository the server knows of, from
its journal and from discovery, with what each gnome is set to there and
whether it is private; each gnome's profiles, what it reads, the
processes it runs and the policies its profiles name; and the policy
deployment in force, where the profiles are defined. ``PUT
/api/settings/{forge}/{owner}/{repo}/{gnome}`` sets one gnome on one
repository, recorded as set by the caller. Both need the role
``SETTINGS_ROLE`` names.

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
from bugflow.method.domain.models.corpus import JUDGE_RUNNER
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
    #: None where discovery has not listed it.
    private: bool | None = None
    #: By gnome. A gnome missing is off and was never set here.
    gnomes: dict[str, GnomeState]


class GnomeAbout(BaseModel):
    """What a gnome is, as the deployment in force says."""

    model_config = ConfigDict(frozen=True)

    #: What its policies read, from its manifest.
    summary: str
    #: Each process that runs it, with when: a pull request's evaluation
    #: for a gnome the judge runs, and each process that names it.
    runs: list[str]
    #: Each profile's policies, by profile name.
    profiles: dict[str, list[str]]
    #: Each of those policies' one-sentence rule, by policy id, where its
    #: policy file gives one.
    policies: dict[str, str]


class DeploymentState(BaseModel):
    """The policy deployment in force, whose profiles.toml defines the
    profiles."""

    model_config = ConfigDict(frozen=True)

    repository: str
    commit: str


class SettingsState(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: Each gnome's profiles, by gnome.
    profiles: dict[str, list[str]]
    repositories: list[RepositoryState]
    #: Each gnome, by gnome.
    gnomes: dict[str, GnomeAbout] = {}
    deployment: DeploymentState | None = None


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
        private=one.private,
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


def _when(cadence: str) -> str:
    return "each pull request" if cadence == "event" else cadence


def _about(reviewers: ReviewersInForce | None) -> dict[str, GnomeAbout]:
    if reviewers is None:
        return {}
    about = {}
    for gnome, named in _profiles(reviewers).items():
        agent = reviewers.agents.get(gnome)
        runs = [
            f"{process.name}, {_when(layer.cadence.name)}"
            for _, layer in sorted(reviewers.layers.items())
            for process in layer.processes
            if process.reviewer == gnome
            or (
                process.reviewer is None
                and process.judges
                and agent is not None
                and agent.runner == JUDGE_RUNNER
            )
        ]
        profiles = {
            name: list(reviewers.profiles[gnome][name]) for name in named
        }
        held = reviewers.policies.get(gnome, {})
        about[gnome] = GnomeAbout(
            summary=agent.summary if agent is not None else "",
            runs=runs,
            profiles=profiles,
            policies={
                policy: held[policy].summary
                for policy in sorted(
                    {p for ps in profiles.values() for p in ps}
                )
                if policy in held
            },
        )
    return about


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
        reviewers = admin.reviewers()
        return SettingsState(
            profiles=_profiles(reviewers),
            repositories=[_state(known[key], held) for key in sorted(known)],
            gnomes=_about(reviewers),
            deployment=DeploymentState(
                repository=reviewers.deployed_from.repository,
                commit=reviewers.deployed_from.commit,
            )
            if reviewers is not None
            else None,
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
