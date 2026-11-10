"""The routes and the page that set each gnome on each repository
(ADR 008).

``GET /api/settings`` lists every repository the server knows of, from
its journal and from discovery, with what each gnome is set to there and
whether it is private; each gnome's profiles, what it reads, the
processes it runs, the policies its profiles name and whose it is; and
each tenant's policy deployment in force, where the profiles are
defined (ADR 011). Each gnome is keyed by its qualified name: its id
for the default tenant's, and ``tenant/id`` for another tenant's, since
two tenants may hold a gnome of one id (ADR 012).
``PUT /api/settings/{forge}/{owner}/{repo}/{gnome}`` sets one gnome on
one repository, recorded as set by the caller; the body names the
tenant where two hold the gnome. Both need the role ``SETTINGS_ROLE``
names.

``GET /settings`` is the page, which signs the person in at the identity
provider in the browser and calls the two routes with the token it is
given. ``GET /settings/config`` tells the page where to sign in. Neither
needs a token: the page holds no data until the routes give it some.
"""

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from importlib.resources import files
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict

from bugflow.apps.shared.boundaries import Defaulted, without_a_boundary
from bugflow.apps.shared.policies import TenantsInForce
from bugflow.apps.shared.setting_tenant import tenant_of_setting
from bugflow.forge.domain.models.forge_repository import KnownRepository
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.method.domain.models.corpus import JUDGE_RUNNER
from bugflow.method.domain.models.policy_deployment import DEFAULT_TENANT
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
    #: Every tenant's reviewers, from its deployment in force.
    reviewers: Callable[[], TenantsInForce]
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
    #: By the gnome's qualified name. A gnome missing is off and was
    #: never set here.
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
    #: The tenant whose deployment in force holds it.
    tenant: str = DEFAULT_TENANT
    #: Its id, which the page sends to set it.
    gnome: str = ""


class DeploymentState(BaseModel):
    """One tenant's policy deployment in force, whose profiles.toml
    defines that tenant's gnomes' profiles."""

    model_config = ConfigDict(frozen=True)

    repository: str
    commit: str
    tenant: str = DEFAULT_TENANT


class SettingsState(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: Each gnome's profiles, by qualified name.
    profiles: dict[str, list[str]]
    repositories: list[RepositoryState]
    #: Each gnome, by qualified name.
    gnomes: dict[str, GnomeAbout] = {}
    #: Each tenant's deployment in force, in tenant order.
    deployments: list[DeploymentState] = []


class SetGnomeBody(BaseModel):
    model_config = ConfigDict(frozen=True)

    behaviour: Behaviour
    #: Omitted, the gnome keeps its profile there, or ``default``.
    profile: str | None = None
    #: Whose gnome it is. Omitted, the one tenant that holds the gnome;
    #: where two do, the setting is refused until one is named.
    tenant: str | None = None


def _state(
    one: KnownRepository, settings: Collection[GnomeSetting]
) -> RepositoryState:
    return RepositoryState(
        forge=one.forge,
        name=one.name,
        archived=one.archived,
        private=one.private,
        gnomes={
            held.qualified: GnomeState(
                behaviour=held.behaviour,
                profile=held.profile,
                set_by=held.set_by,
                set_at=held.set_at.isoformat() if held.set_at else None,
            )
            for held in settings
            if (held.forge, held.repo) == (one.forge, one.name)
        },
    )


def _offered(named: Iterable[str]) -> list[str]:
    return sorted(named, key=lambda name: (name != DEFAULT_PROFILE, name))


def _profiles(held: TenantsInForce) -> dict[str, list[str]]:
    return {
        name: _offered(named) for name, named in sorted(held.profiles.items())
    }


def _when(cadence: str) -> str:
    return "each pull request" if cadence == "event" else cadence


def _about(held: TenantsInForce) -> dict[str, GnomeAbout]:
    about = {}
    agents, policies, whose = held.agents, held.policies, held.gnomes
    for name, named in _profiles(held).items():
        tenant, gnome = whose[name]
        agent = agents.get(name)
        # The processes of the gnome's own tenant: another tenant's
        # process never runs it.
        runs = [
            f"{process.name}, {_when(layer.cadence.name)}"
            for _, layer in sorted(held.layers_of(tenant).items())
            for process in layer.processes
            if process.reviewer == gnome
            or (
                process.reviewer is None
                and process.judges
                and agent is not None
                and agent.runner == JUDGE_RUNNER
            )
        ]
        profiles = {one: list(held.profiles[name][one]) for one in named}
        texts = policies.get(name, {})
        about[name] = GnomeAbout(
            summary=agent.summary if agent is not None else "",
            runs=runs,
            profiles=profiles,
            policies={
                policy: texts[policy].summary
                for policy in sorted(
                    {p for ps in profiles.values() for p in ps}
                )
                if policy in texts
            },
            tenant=tenant,
            gnome=gnome,
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
            deployments=[
                DeploymentState(
                    repository=came_from.repository,
                    commit=came_from.commit,
                    tenant=tenant,
                )
                for tenant, came_from in sorted(reviewers.deployed.items())
            ],
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
        if not reviewers.by_tenant and body.behaviour != "off":
            raise HTTPException(
                409, "no policy deployment is in force, so no gnome can judge"
            )
        held = admin.settings.settings_of(forge, name)
        try:
            tenant = tenant_of_setting(reviewers, gnome, held, body.tenant)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if body.behaviour != "off" and reviewers.by_tenant:
            # The layers of the gnome's own tenant, whose worker is
            # what would refuse to start.
            layers = reviewers.layers_of(tenant)
            watched = f"{forge}:{name}" if forge != "github" else name
            missing = without_a_boundary(
                layers, [watched], Defaulted(admin.boundaries, layers)
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
                for one in held
                if (one.gnome, one.tenant) == (gnome, tenant)
            ),
            None,
        )
        offered = reviewers.profiles_of(tenant)
        profile = body.profile or (kept.profile if kept else DEFAULT_PROFILE)
        if body.profile is None and profile not in offered.get(gnome, ()):
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
                    tenant=tenant,
                    set_by=who.subject,
                    profiles=offered,
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
