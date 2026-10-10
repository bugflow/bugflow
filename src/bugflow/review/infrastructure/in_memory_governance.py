"""Governance held in memory: a default, overridden per repository.

The Postgres adapter reads the same shape from the database, because a
staged rollout is operational data that changes without a release: one
team governed by an agent while another is not yet, with the default the
answer for everything nobody has said otherwise about.
"""

from collections.abc import Iterable, Mapping


class InMemoryGovernance:
    def __init__(
        self,
        default: Iterable[str] = (),
        overrides: Mapping[tuple[str, str], Iterable[str]] | None = None,
    ) -> None:
        self._default = frozenset(default)
        self._overrides = {
            key: frozenset(agents) for key, agents in (overrides or {}).items()
        }

    def governing_agents(self, forge: str, repo: str) -> frozenset[str]:
        return self._overrides.get((forge, repo), self._default)
