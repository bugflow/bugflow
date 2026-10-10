"""The interface that reads the topology of feedback loops.

Which processes a layer holds, and at what cadence. It is the method's,
so it is read from the deployment rather than from a repository's
declarations: a repository declares which processes apply to it, and a
run works its own subject out from that.
"""

from collections.abc import Mapping
from typing import Protocol

from bugflow.method.domain.models.pace_layer import PaceLayer
from bugflow.shared.domain.repositories.base import BaseRepository


class PaceLayerTopologyRepository(BaseRepository[PaceLayer], Protocol):
    def layers(self) -> Mapping[str, PaceLayer]:
        """Every layer, keyed by name, in name order."""
        ...
