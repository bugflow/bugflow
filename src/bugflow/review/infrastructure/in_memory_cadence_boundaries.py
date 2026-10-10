"""Where this server's periods begin, kept in memory, for tests."""

from bugflow.review.domain.models.cadence_boundary import CadenceBoundary


class InMemoryCadenceBoundaries:
    def __init__(self) -> None:
        self.declared: dict[str, str] = {}

    def boundary(self, cadence: str) -> str | None:
        return self.declared.get(cadence)

    def declarations(self) -> list[CadenceBoundary]:
        return [
            CadenceBoundary(cadence=cadence, boundary=at)
            for cadence, at in sorted(self.declared.items())
        ]

    def declare(self, boundary: CadenceBoundary) -> None:
        self.declared[boundary.cadence] = boundary.boundary

    def withdraw(self, cadence: str) -> None:
        self.declared.pop(cadence, None)
