"""Where each repository's periods begin, kept in memory, for tests."""

from bugflow.review.domain.models.layer_boundary import LayerBoundary


class InMemoryLayerBoundaries:
    def __init__(self) -> None:
        self.declared: dict[tuple[str, str, str], str] = {}

    def boundary(self, forge: str, repo: str, layer: str) -> str | None:
        return self.declared.get((forge, repo, layer))

    def declarations(self) -> list[LayerBoundary]:
        return [
            LayerBoundary(forge=forge, repo=repo, layer=layer, boundary=at)
            for (forge, repo, layer), at in sorted(self.declared.items())
        ]

    def declare(self, boundary: LayerBoundary) -> None:
        self.declared[(boundary.forge, boundary.repo, boundary.layer)] = (
            boundary.boundary
        )

    def withdraw(self, forge: str, repo: str, layer: str) -> None:
        self.declared.pop((forge, repo, layer), None)
