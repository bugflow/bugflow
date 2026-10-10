"""What share of each repository's warnings is withheld, held in memory,
for tests."""

from bugflow.review.domain.models.withholding import Withholding


class InMemoryWithholding:
    def __init__(self) -> None:
        self._declared: dict[tuple[str, str], Withholding] = {}

    def share_for(self, forge: str, repo: str) -> float:
        declared = self._declared.get((forge, repo))
        return declared.share if declared else 0.0

    def declarations(self) -> list[Withholding]:
        return [self._declared[key] for key in sorted(self._declared)]

    def declare(self, withholding: Withholding) -> None:
        self._declared[(withholding.forge, withholding.repo)] = withholding
