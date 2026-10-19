"""A store of bindings kept in memory, for tests."""

from bugflow.archive.domain.models.binding import (
    ArchiveBinding,
    check_binding_origin,
)


class InMemoryBindings:
    def __init__(self) -> None:
        self._bound: dict[str, ArchiveBinding] = {}

    def for_ledger(self, ledger_id: str) -> ArchiveBinding | None:
        return self._bound.get(ledger_id)

    def bindings(self) -> list[ArchiveBinding]:
        return sorted(
            self._bound.values(),
            key=lambda b: (b.forge, b.repo, b.scope, b.ledger_id),
        )

    def save(self, binding: ArchiveBinding) -> None:
        previous = self.for_ledger(binding.ledger_id)
        check_binding_origin(binding, previous.origin if previous else None)
        self._bound[binding.ledger_id] = binding
