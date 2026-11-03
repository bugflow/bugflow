"""Which repository and layer pairs have said where their periods begin.

A cadence is a frequency, which the method declares; where a period
starts is declared per repository per layer, in the review records. The
two meet here, because neither context may read the other.

A boundary may not be unset. Silence about one does not fail, it
guesses: a weekly allowance that assumes Monday midnight while the
stocktake reads 23:30 Sunday charges a run to the week about to end, and
nothing says so until the money is counted. So a pair with no boundary
stops the worker, rather than running on a guess. A layer may state a
default boundary for every repository that declares none (ADR 008),
which is a statement and not a guess; ``Defaulted`` answers with it.

``Boundaries`` works out the period an allowance is counted over, for
the worker that refuses a run and for a page that shows what is left.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bugflow.apps.shared.policies import ReviewersInForce
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.method.domain.models.boundary import (
    BoundaryError,
    phase,
    settling_window,
)
from bugflow.method.domain.models.pace_layer import CADENCES, PaceLayer
from bugflow.review.domain.models.layer_boundary import LayerBoundary
from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.domain.services.cadence_boundaries import (
    CadenceBoundariesService,
)
from bugflow.review.domain.services.layer_boundaries import (
    LayerBoundariesService,
)
from bugflow.review.infrastructure.sqlalchemy_cadence_boundaries import (
    SqlAlchemyCadenceBoundaries,
)
from bugflow.review.infrastructure.sqlalchemy_layer_boundaries import (
    SqlAlchemyLayerBoundaries,
)
from bugflow.shared.domain.values.budget import period


class Defaulted:
    """Implements ``LayerBoundariesService``: each repository's declared
    boundary on a layer, or the layer's default where it declared none.
    What is declared is unchanged."""

    def __init__(
        self,
        declared: LayerBoundariesService,
        layers: Mapping[str, PaceLayer],
    ) -> None:
        self._declared = declared
        self._layers = layers

    def boundary(self, forge: str, repo: str, layer: str) -> str | None:
        found = self._declared.boundary(forge, repo, layer)
        if found is not None:
            return found
        held = self._layers.get(layer)
        return held.default_boundary if held else None

    def declare(self, boundary: LayerBoundary) -> None:
        self._declared.declare(boundary)

    def withdraw(self, forge: str, repo: str, layer: str) -> None:
        self._declared.withdraw(forge, repo, layer)

    def declarations(self) -> list[LayerBoundary]:
        return self._declared.declarations()


def without_a_boundary(
    layers: Mapping[str, PaceLayer],
    watched: Iterable[str],
    boundaries: LayerBoundariesService,
) -> list[str]:
    """Every watched repository and layer that has declared none.
    ``watched`` names each repository as ``owner/repo`` for GitHub or
    ``forgejo:owner/repo`` for Forgejo.

    Both kinds of layer, because both have a boundary: a clock layer is
    bounded by its phase and an event layer by the window its signals
    settle in, and a run charged to the wrong period is the same defect
    either way.
    """
    missing = []
    for one in sorted(set(watched)):
        if not one:
            continue
        repository = WatchedRepository.parse(one)
        forge, repo = repository.forge, f"{repository.owner}/{repository.repo}"
        for name in sorted(layers):
            if boundaries.boundary(forge, repo, name) is None:
                missing.append(f"{forge}:{repo} on {name}")
    return missing


def refuse_without_a_boundary(
    layers: Mapping[str, PaceLayer],
    watched: Iterable[str],
    boundaries: LayerBoundariesService,
) -> None:
    """Stop the worker rather than run a period nobody has bounded."""
    missing = without_a_boundary(layers, watched, boundaries)
    if not missing:
        return
    raise ValueError(
        "no boundary declared for "
        + "; ".join(missing)
        + ". A period with no boundary is one whose start nobody stated. "
        "Declare one for each repository on each layer with `bugflow "
        "declare REPOSITORY --layer LAYER --boundary BOUNDARY`. For a "
        "layer an event fires, the boundary is the window a burst of "
        "deliveries settles in, in seconds, such as 60s. For a layer a "
        "clock fires, it is where the period begins: a time, a day and a "
        "time, a day of the month and a time, or a date and a time, such "
        "as SUN 23:30"
    )


def settling_for(
    layers: Mapping[str, PaceLayer],
    boundaries: LayerBoundariesService,
) -> Callable[[str, str], float | None]:
    """How long a burst of deliveries settles for, per repository.

    An event cadence is bounded by the window its signals settle in, and
    that window is the repository's to declare, as a clock cadence's
    phase is. Five pushes inside it are one event and one run.

    Answers None where the repository has declared none, and where no
    layer rides an event cadence: the workflow then waits its own
    default, which is what a run already in flight waits too.
    """
    event = [
        name for name, layer in layers.items() if not layer.cadence.on_a_clock
    ]

    def declared(forge: str, repo: str) -> float | None:
        for name in sorted(event):
            found = boundaries.boundary(forge, repo, name)
            if found is not None:
                return float(settling_window(found).seconds)
        return None

    return declared


#: The timezone a calendar period starts and ends in when the
#: ``PERIODS_TIMEZONE`` setting is not given.
DEFAULT_PERIODS_TIMEZONE = "UTC"


def periods_timezone(environ: Mapping[str, str]) -> str:
    """Read the timezone a calendar period starts and ends in.

    Setting: ``PERIODS_TIMEZONE``, an IANA name such as
    ``Europe/Lisbon``. It defaults to ``UTC``. A server has one, so that
    a day's allowance and a weekly run are counted on the same clock.

    Raises ``ValueError`` if the name is not a timezone.
    """
    name = environ.get("PERIODS_TIMEZONE") or DEFAULT_PERIODS_TIMEZONE
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(
            f"PERIODS_TIMEZONE is {name!r}, which is not a timezone"
        ) from exc
    return name


@dataclass(frozen=True)
class Boundaries:
    """Where the periods an allowance is counted over begin.

    A boundary belongs to the repository whose period it bounds, and an
    allowance may be scoped wider than any repository. So two
    declarations answer, and this is where they meet: the repository's
    if the allowance names one repository and one layer riding the
    cadence it is counted per, and the deployment's otherwise.

    The layers are here because a boundary is declared per layer and an
    allowance is counted per cadence, and only the topology says which
    layer rides which.
    """

    layers: Mapping[str, PaceLayer]
    repositories: LayerBoundariesService | None = None
    deployment: CadenceBoundariesService | None = None
    #: The timezone a calendar period starts and ends in, as
    #: ``periods_timezone`` reads it.
    zone: str = DEFAULT_PERIODS_TIMEZONE

    def bounding(self, binding: SpendBinding) -> str | None:
        """Return where this allowance's periods begin, or None if
        nothing has said."""
        scope = binding.scope
        layer = self.layers.get(scope.layer)
        if (
            self.repositories is not None
            and scope.forge
            and scope.repo
            and layer is not None
            and layer.cadence.name == binding.per
        ):
            declared = self.repositories.boundary(
                scope.forge, scope.repo, scope.layer
            )
            if declared is not None:
                return declared
        if self.deployment is None:
            return None
        return self.deployment.boundary(binding.per)

    def window(
        self, binding: SpendBinding, now: datetime
    ) -> tuple[datetime, datetime] | None:
        """Return the period of this allowance that contains ``now``.

        None if the cadence has no span, which is the cadence no clock
        fires: a per-event allowance is the ceiling handed to the run
        and not a question about what was already spent.

        Raises ``BoundaryError`` if nothing says where the period
        begins.
        """
        cadence = CADENCES.get(binding.per)
        if cadence is None or not cadence.span:
            return None
        declared = self.bounding(binding)
        if declared is None:
            raise BoundaryError(
                f"nothing says where a {binding.per} period begins for "
                f"{where_named(binding.scope) or 'everything'}"
            )
        begins = phase(declared, cadence.span, now, self.zone)
        return period(cadence.span, begins.at, now)


def where_named(scope: SpendScope) -> str:
    """Name the scope as a person does, for a refusal that has to be
    read."""
    return " ".join(
        part
        for part in (
            f"{scope.forge}:{scope.repo}" if scope.repo else "",
            f"{scope.forge}:{scope.owner}/*" if scope.owner else "",
            scope.layer,
            scope.agent_id,
        )
        if part
    )


def boundaries_from_environment(
    environ: Mapping[str, str], reviewers: ReviewersInForce
) -> Boundaries:
    """Build where the periods an allowance is counted over begin: each
    repository's declaration, this server's own, the layers that join
    them, and the timezone ``PERIODS_TIMEZONE`` names."""
    database_url = environ["DATABASE_URL"]
    return Boundaries(
        layers=reviewers.layers,
        repositories=Defaulted(
            SqlAlchemyLayerBoundaries(database_url), reviewers.layers
        ),
        deployment=SqlAlchemyCadenceBoundaries(database_url),
        zone=periods_timezone(environ),
    )
