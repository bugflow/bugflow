"""Which repository and layer pairs have said where their periods begin.

A cadence is a frequency, which the method declares; where a period
starts is declared per repository per layer, in the review records. The
two meet here, because neither context may read the other.

A boundary may not be unset. Silence about one does not fail, it
guesses: a weekly allowance that assumes Monday midnight while the
stocktake reads 23:30 Sunday charges a run to the week about to end, and
nothing says so until the money is counted. So a pair with no boundary
stops the worker, rather than running on a guess.
"""

from collections.abc import Callable, Iterable, Mapping

from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.method.domain.models.boundary import settling_window
from bugflow.method.domain.models.pace_layer import PaceLayer
from bugflow.review.domain.services.layer_boundaries import (
    LayerBoundariesService,
)


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
        + ". A period with no boundary is one whose start nobody stated: "
        "declare one for each repository on each layer"
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
