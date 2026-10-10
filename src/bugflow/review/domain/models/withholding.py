"""The share of a repository's warnings kept from its pull requests.

Withheld warnings are the control arm: what happens to a warning nobody
read, against what happens to one somebody could have. The share is the
repository's to set, because it costs the author that warning, and a
repository that has declared none withholds nothing.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class Withholding:
    forge: str
    repo: str
    #: Of the warnings raised on this repository, the share drawn to be
    #: withheld: 0 withholds none and 1 withholds every one.
    share: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.share <= 1.0:
            raise ValueError(
                f"a share is between 0 and 1, not {self.share}: it is the "
                "part of the warnings that is withheld"
            )
