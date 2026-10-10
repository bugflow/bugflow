"""What a repository is reviewed for, kept in memory, for tests."""

from bugflow.review.domain.models.review_declaration import (
    DispatchedProcesses,
    JudgedPolicies,
)


class InMemoryJudgedPolicies:
    def __init__(self) -> None:
        self.declared: dict[tuple[str, str], tuple[str, ...]] = {}

    def judged(self, forge: str, repo: str) -> frozenset[str]:
        return frozenset(self.declared.get((forge, repo), ()))

    def declarations(self) -> list[JudgedPolicies]:
        return [
            JudgedPolicies(forge=forge, repo=repo, policies=names)
            for (forge, repo), names in sorted(self.declared.items())
        ]

    def declare(self, declaration: JudgedPolicies) -> None:
        self.declared[(declaration.forge, declaration.repo)] = tuple(
            dict.fromkeys(declaration.policies)
        )


class InMemoryDispatchedProcesses:
    def __init__(self) -> None:
        self.declared: dict[tuple[str, str], tuple[str, ...]] = {}

    def dispatched(self, forge: str, repo: str) -> frozenset[str]:
        return frozenset(self.declared.get((forge, repo), ()))

    def declarations(self) -> list[DispatchedProcesses]:
        return [
            DispatchedProcesses(forge=forge, repo=repo, processes=names)
            for (forge, repo), names in sorted(self.declared.items())
        ]

    def declare(self, declaration: DispatchedProcesses) -> None:
        self.declared[(declaration.forge, declaration.repo)] = tuple(
            dict.fromkeys(declaration.processes)
        )
