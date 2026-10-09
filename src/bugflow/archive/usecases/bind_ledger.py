"""Use case: bind a ledger to a scope of a repository.

Only this binds one. A ledger nobody bound is kept for no one,
so a client with a repository's commit access cannot start a new ledger
and have it kept in the scope's name: an operator has to say so, here,
and the saying is a fact in the journal. Binding a ledger again
elsewhere, or a second ledger to a scope that has one, is the same act
and recorded the same way, with what it replaced or stands beside.
"""

from bugflow.archive.domain import facts
from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.archive.domain.repositories.bindings import BindingRepository
from bugflow.archive.dtos.bind_ledger import (
    BindLedgerRequest,
    BindLedgerResponse,
    BoundTo,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService

# A binding is declared by an operator at a command line, not run in a
# workflow, so it carries a correlation naming what recorded it.
WORKFLOW_ID = "archive/bound"


class BindLedgerUseCase:
    """Given a ledger and a scope of a repository, answers with whether
    the binding was made, what it replaced, and which other ledgers the
    scope already had."""

    def __init__(
        self,
        bindings: BindingRepository,
        journal: RecordingService,
        clock: ClockService,
        run_id: str,
    ) -> None:
        self._bindings = bindings
        self._journal = journal
        self._clock = clock
        self._run_id = run_id

    def execute(self, request: BindLedgerRequest) -> BindLedgerResponse:
        binding = ArchiveBinding(
            ledger_id=request.ledger_id,
            forge=request.forge,
            repo=request.repo,
            scope=request.scope,
        )
        previous = self._bindings.for_ledger(binding.ledger_id)
        beside = tuple(
            sorted(
                other.ledger_id
                for other in self._bindings.bindings()
                if other.ledger_id != binding.ledger_id
                and (other.forge, other.repo, other.scope)
                == (binding.forge, binding.repo, binding.scope)
            )
        )
        bound = previous != binding
        if bound:
            # The fact first, the row second: a row whose fact could not
            # be written would be a binding nobody can be shown was made,
            # and a second attempt would find it made and record nothing.
            self._journal.append([self._entry(binding, previous, beside)])
            self._bindings.save(binding)
        return BindLedgerResponse(
            ledger_id=binding.ledger_id,
            forge=binding.forge,
            repo=binding.repo,
            scope=binding.scope,
            bound=bound,
            replaces=_bound_to(previous) if bound and previous else None,
            beside=beside,
        )

    def _entry(
        self,
        binding: ArchiveBinding,
        previous: ArchiveBinding | None,
        beside: tuple[str, ...],
    ) -> JournalEntry:
        when = self._clock.now()
        replaced = _bound_to(previous) if previous else None
        return JournalEntry(
            event_id=facts.bound_id(
                binding.ledger_id,
                binding.forge,
                binding.repo,
                binding.scope,
                when,
            ),
            occurred_at=when,
            event_type=facts.BOUND,
            forge=binding.forge,
            repo=binding.repo,
            pr_number=None,
            commit_sha=None,
            corpus_version=None,
            workflow_id=WORKFLOW_ID,
            run_id=self._run_id,
            payload={
                "ledger_id": binding.ledger_id,
                "scope": binding.scope,
                "replaces": replaced.model_dump() if replaced else None,
                "beside": list(beside),
            },
        )


def _bound_to(binding: ArchiveBinding) -> BoundTo:
    return BoundTo(forge=binding.forge, repo=binding.repo, scope=binding.scope)
