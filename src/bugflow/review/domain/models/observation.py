"""What this context reads of an observation of a pull request, the
forge's ``pr.observed`` fact: which run took it, of which commit and
under which corpus version, and the stored submission it read. The
forge's table holds the rest of the observation (ADR 007).
"""

from dataclasses import dataclass

from bugflow.shared.domain.values.correlation import Correlation


@dataclass(frozen=True, kw_only=True)
class Observation:
    correlation: Correlation
    commit_sha: str | None
    corpus_version: str | None
    #: The id of the stored submission the observation read.
    snapshot_id: str
