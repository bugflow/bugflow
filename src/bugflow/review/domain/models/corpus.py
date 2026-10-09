"""The corpus an evaluation runs under: the doctrine and the judge's
settings, and the version made from them."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from bugflow.review.domain.models.doctrine import DoctrineText


@dataclass(frozen=True, kw_only=True)
class Corpus:
    doctrine: DoctrineText
    #: A hash of the judge's model and the source of its adapter. None
    #: if no judge is set up.
    judge: str | None
    #: The corpus version of each installed reviewer, by agent id. A
    #: reviewer has a version of its own because it has doctrine and
    #: policies of its own.
    installed: Mapping[str, str] = field(default_factory=dict)
    #: The reviewer that judged and checked findings are recorded under.
    #: Empty if none is installed.
    reporting_agent: str = ""

    def components(self) -> dict[str, str | None]:
        """The two things the version is made from."""
        return {
            "doctrine": self.doctrine.version,
            "judge": self.judge,
        }

    @property
    def version(self) -> str:
        """The first 12 hexadecimal characters of a hash of the
        components."""
        canonical = json.dumps(self.components(), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:12]

    def version_for(self, agent_id: str) -> str:
        """The version that this reviewer's findings are recorded under:
        its own if it is installed, and this corpus's otherwise."""
        return self.installed.get(agent_id) or self.version
