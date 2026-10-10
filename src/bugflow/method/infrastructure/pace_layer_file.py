"""Read the topology of feedback loops from a TOML file.

The file sits beside the reviewers in a policy repository, because the
topology is the method's: it changes when the method changes, by a
commit and a deploy.

The shape is two tables::

    [process.evaluate-pull-request]
    subject = "pull request"
    judges = true

    [layer.pull-request]
    cadence = "event"
    processes = ["evaluate-pull-request"]

    [process.security-stocktake]
    subject = "range"
    reviewer = "security"

    [layer.weekly]
    cadence = "weekly"
    processes = ["security-stocktake"]

``reviewer`` names a reviewer dispatched at a worktree; ``judges`` says
the judge reads the same subject in the evaluation itself. A process
may have either, both or neither.

A key neither table defines is refused rather than ignored, so a layer
that tried to name a repository fails here and says so: a layer holds
processes, and a run works its subject out from what the repositories
declare.
"""

import functools
import tomllib
from collections.abc import Callable
from pathlib import Path

from bugflow.method.domain.errors import PaceLayerTopologyError
from bugflow.method.domain.models.pace_layer import (
    PaceLayer,
    Process,
    layer,
    process,
)
from bugflow.shared.domain.values.budget import Budget
from bugflow.shared.infrastructure.toml_validation import require

_require = functools.partial(require, error=PaceLayerTopologyError)

_PROCESS_KEYS = frozenset({"subject", "reviewer", "usd", "turns", "judges"})
_LAYER_KEYS = frozenset({"cadence", "processes"})
_TABLES = frozenset({"process", "layer"})


class FilePaceLayerTopology:
    """Implements ``PaceLayerTopologyRepository`` over one file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def layers(self) -> dict[str, PaceLayer]:
        """Every layer the file declares, or none if there is no file.

        A server with no topology holds no layer and runs no process. A
        file that is there and declares no layer is still refused,
        because that is a mistake in a file somebody wrote.
        """
        if not self._path.is_file():
            return {}
        return read_topology(self._path)


def read_topology(path: Path) -> dict[str, PaceLayer]:
    """Every layer the file declares, keyed by name, in name order."""
    return parse_topology(path, path.read_text())


def parse_topology(path: Path, text: str) -> dict[str, PaceLayer]:
    """Every layer the text declares, keyed by name, in name order.

    ``path`` names where the text came from, for an error to cite. The
    text need not be on disk: a deployment holds it in the database.

    Raises ``PaceLayerTopologyError`` for a table nothing defines, a key
    nothing defines, a cadence or a subject nobody defined, a layer
    naming a process nobody declared, and a layer holding none.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PaceLayerTopologyError(path, str(exc)) from exc
    _no_other_key(path, "the topology", document, _TABLES)
    processes = {
        name: _process(path, name, table)
        for name, table in _entries(path, document, "process")
    }
    layers = {
        name: _layer(path, name, table, processes)
        for name, table in _entries(path, document, "layer")
    }
    if not layers:
        raise PaceLayerTopologyError(path, "no layer is declared")
    return layers


def _entries(
    path: Path, document: dict[str, object], table: str
) -> list[tuple[str, dict[str, object]]]:
    """The named tables under ``[<table>.<name>]``, in name order."""
    held = document.get(table, {})
    if not isinstance(held, dict):
        raise PaceLayerTopologyError(
            path, f"{table} must be a table, got {type(held).__name__}"
        )
    entries = []
    for name, entry in sorted(held.items()):
        if not isinstance(entry, dict):
            raise PaceLayerTopologyError(
                path,
                f"{table}.{name} must be a table, got {type(entry).__name__}",
            )
        entries.append((name, entry))
    return entries


def _no_other_key(
    path: Path, what: str, table: dict[str, object], known: frozenset[str]
) -> None:
    other = sorted(set(table) - known)
    if other:
        raise PaceLayerTopologyError(
            path,
            f"{what} declares {', '.join(other)}, which it has no key "
            f"for; it has {', '.join(sorted(known))}",
        )


def _process(path: Path, name: str, table: dict[str, object]) -> Process:
    _no_other_key(path, f"the process {name!r}", table, _PROCESS_KEYS)
    subject = _require(path, table, "subject", str)
    reviewer = (
        _require(path, table, "reviewer", str) if "reviewer" in table else None
    )
    # Both or neither: a ceiling naming money and not turns would let a
    # looping run spend the money slowly, and one naming turns and not
    # money would do the reverse.
    worth = (
        Budget(
            usd=_require(path, table, "usd", float),
            turns=_require(path, table, "turns", float),
        )
        if "usd" in table or "turns" in table
        else None
    )
    judges = (
        _require(path, table, "judges", bool) if "judges" in table else False
    )
    return _refusing(
        path, lambda: process(name, subject, reviewer, worth, judges)
    )


def _layer(
    path: Path,
    name: str,
    table: dict[str, object],
    processes: dict[str, Process],
) -> PaceLayer:
    _no_other_key(path, f"the layer {name!r}", table, _LAYER_KEYS)
    cadence = _require(path, table, "cadence", str)
    held = _require(path, table, "processes", list)
    named = [one for one in held if isinstance(one, str)]
    if len(named) != len(held):
        raise PaceLayerTopologyError(
            path, f"the layer {name!r} names a process that is not a string"
        )
    return _refusing(path, lambda: layer(name, cadence, named, processes))


def _refusing[T](path: Path, build: Callable[[], T]) -> T:
    """What the domain refuses, said with the file that declared it."""
    try:
        return build()
    except PaceLayerTopologyError:
        raise
    except ValueError as exc:
        raise PaceLayerTopologyError(path, str(exc)) from exc
