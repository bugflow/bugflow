"""What a repository's declared boundaries say to a program: how long a
burst of deliveries settles for, and which pairs have declared nothing.
"""

import pytest

from bugflow.apps.shared.boundaries import (
    refuse_without_a_boundary,
    settling_for,
    without_a_boundary,
)
from bugflow.method.domain.models.pace_layer import (
    EVENT,
    NIGHTLY,
    PaceLayer,
)
from bugflow.review.domain.models.layer_boundary import LayerBoundary
from bugflow.review.infrastructure.in_memory_layer_boundaries import (
    InMemoryLayerBoundaries,
)

LAYERS = {
    "each-change": PaceLayer(name="each-change", cadence=EVENT, processes=()),
    "each-night": PaceLayer(name="each-night", cadence=NIGHTLY, processes=()),
}


def declared(*boundaries: LayerBoundary) -> InMemoryLayerBoundaries:
    held = InMemoryLayerBoundaries()
    for one in boundaries:
        held.declare(one)
    return held


def test_a_declared_window_is_the_seconds_a_burst_settles_for() -> None:
    boundaries = declared(
        LayerBoundary(
            forge="github", repo="o/r", layer="each-change", boundary="300s"
        )
    )
    assert settling_for(LAYERS, boundaries)("github", "o/r") == 300.0


def test_a_repository_that_declared_none_leaves_the_default() -> None:
    assert settling_for(LAYERS, declared())("github", "o/r") is None


def test_a_clock_layers_boundary_is_not_a_window() -> None:
    """Only a layer an event fires bounds a burst. A nightly layer's
    boundary is a time of day, and says nothing about settling."""
    boundaries = declared(
        LayerBoundary(
            forge="github", repo="o/r", layer="each-night", boundary="23:30"
        )
    )
    assert settling_for(LAYERS, boundaries)("github", "o/r") is None


def test_every_undeclared_pair_is_named() -> None:
    boundaries = declared(
        LayerBoundary(
            forge="github", repo="o/r", layer="each-change", boundary="60s"
        )
    )
    assert without_a_boundary(
        LAYERS, ["o/r", "forgejo:o/other", ""], boundaries
    ) == [
        "forgejo:o/other on each-change",
        "forgejo:o/other on each-night",
        "github:o/r on each-night",
    ]


def test_a_pair_with_no_boundary_stops_the_program() -> None:
    with pytest.raises(ValueError, match="github:o/r on each-change"):
        refuse_without_a_boundary(LAYERS, ["github:o/r"], declared())


def test_every_pair_declared_lets_the_program_start() -> None:
    boundaries = declared(
        LayerBoundary(
            forge="github", repo="o/r", layer="each-change", boundary="60s"
        ),
        LayerBoundary(
            forge="github", repo="o/r", layer="each-night", boundary="23:30"
        ),
    )
    refuse_without_a_boundary(LAYERS, ["o/r"], boundaries)
