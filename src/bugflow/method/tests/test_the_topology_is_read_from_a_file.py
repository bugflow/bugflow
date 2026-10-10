"""Tests of the topology of feedback loops as its file declares it.

What the file declares is refused when it is read, so a cadence nobody
defined is not discovered at the first run.
"""

from pathlib import Path

import pytest

from bugflow.method.domain.errors import PaceLayerTopologyError
from bugflow.method.domain.models.pace_layer import EVENT
from bugflow.method.infrastructure.pace_layer_file import (
    FilePaceLayerTopology,
    read_topology,
)

DECLARED = """
[process.architecture-stocktake]
subject = "range"

[process.evaluate-pull-request]
subject = "pull request"

[process.collect-at-close]
subject = "pull request"

[layer.weekly]
cadence = "weekly"
processes = ["architecture-stocktake"]

[layer.pull-request]
cadence = "event"
processes = ["evaluate-pull-request", "collect-at-close"]
"""


def written(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "pace-layers.toml"
    path.write_text(text)
    return path


def test_a_layer_holds_the_processes_the_file_gives_it(
    tmp_path: Path,
) -> None:
    layers = read_topology(written(tmp_path, DECLARED))

    assert sorted(layers) == ["pull-request", "weekly"]
    assert layers["weekly"].cadence.on_a_clock is True
    assert [one.name for one in layers["weekly"].processes] == [
        "architecture-stocktake"
    ]
    assert layers["pull-request"].cadence is EVENT


def test_the_order_of_the_file_is_not_a_layers_identity(
    tmp_path: Path,
) -> None:
    """A layer is what it is named and what it holds. The same
    declarations written in another order are the same topology."""
    shuffled = "\n\n".join(reversed(DECLARED.strip().split("\n\n"))).replace(
        '["evaluate-pull-request", "collect-at-close"]',
        '["collect-at-close", "evaluate-pull-request"]',
    )
    other = tmp_path / "other"
    other.mkdir()

    assert read_topology(written(other, shuffled)) == read_topology(
        written(tmp_path, DECLARED)
    )


def test_a_cadence_nobody_defined_is_refused(tmp_path: Path) -> None:
    text = DECLARED.replace('cadence = "weekly"', 'cadence = "sprintly"')

    with pytest.raises(PaceLayerTopologyError, match="sprintly"):
        read_topology(written(tmp_path, text))


def test_a_process_nobody_declared_is_refused(tmp_path: Path) -> None:
    text = DECLARED.replace(
        'processes = ["architecture-stocktake"]',
        'processes = ["test-suite-stocktake"]',
    )

    with pytest.raises(PaceLayerTopologyError, match="test-suite-stocktake"):
        read_topology(written(tmp_path, text))


def test_a_layer_holding_no_process_is_refused(tmp_path: Path) -> None:
    text = DECLARED.replace(
        'processes = ["architecture-stocktake"]', "processes = []"
    )

    with pytest.raises(PaceLayerTopologyError, match="holds no process"):
        read_topology(written(tmp_path, text))


def test_a_layer_that_names_a_repository_is_refused(
    tmp_path: Path,
) -> None:
    text = DECLARED.replace(
        'cadence = "weekly"',
        'cadence = "weekly"\nrepositories = ["example/repository"]',
    )

    with pytest.raises(PaceLayerTopologyError, match="repositories"):
        read_topology(written(tmp_path, text))


def test_a_topology_that_declares_anything_else_is_refused(
    tmp_path: Path,
) -> None:
    text = f'{DECLARED}\n[server]\nwatching = ["example/repository"]\n'

    with pytest.raises(PaceLayerTopologyError, match="server"):
        read_topology(written(tmp_path, text))


def test_a_file_declaring_no_layer_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PaceLayerTopologyError, match="no layer"):
        read_topology(written(tmp_path, "[process.a]\nsubject = 'range'\n"))


def test_a_process_declares_whether_the_judge_reads_it(
    tmp_path: Path,
) -> None:
    text = DECLARED.replace(
        '[process.evaluate-pull-request]\nsubject = "pull request"',
        '[process.evaluate-pull-request]\nsubject = "pull request"\n'
        "judges = true",
    )

    layers = read_topology(written(tmp_path, text))

    holds = {one.name: one for one in layers["pull-request"].processes}
    assert holds["evaluate-pull-request"].judges
    assert not holds["collect-at-close"].judges


def test_a_process_that_says_nothing_does_not_judge(tmp_path: Path) -> None:
    layers = read_topology(written(tmp_path, DECLARED))

    assert not any(
        one.judges for layer in layers.values() for one in layer.processes
    )


def test_judging_declared_as_anything_but_a_flag_is_refused(
    tmp_path: Path,
) -> None:
    text = DECLARED.replace(
        '[process.evaluate-pull-request]\nsubject = "pull request"',
        '[process.evaluate-pull-request]\nsubject = "pull request"\n'
        'judges = "yes"',
    )

    with pytest.raises(PaceLayerTopologyError, match="judges"):
        read_topology(written(tmp_path, text))


def test_a_process_may_say_what_it_is_worth(tmp_path: Path) -> None:
    text = DECLARED.replace(
        '[process.architecture-stocktake]\nsubject = "range"',
        '[process.architecture-stocktake]\nsubject = "range"\n'
        "usd = 20.0\nturns = 200.0",
    )

    layers = read_topology(written(tmp_path, text))

    (stocktake,) = layers["weekly"].processes
    assert stocktake.worth is not None
    assert (stocktake.worth.usd, stocktake.worth.turns) == (20.0, 200.0)


def test_a_server_with_no_topology_file_holds_no_layer(tmp_path: Path) -> None:
    assert FilePaceLayerTopology(tmp_path / "pace-layers.toml").layers() == {}


def test_a_file_that_declares_no_layer_is_still_refused(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "pace-layers.toml"
    empty.write_text("")

    with pytest.raises(PaceLayerTopologyError, match="no layer is declared"):
        FilePaceLayerTopology(empty).layers()
