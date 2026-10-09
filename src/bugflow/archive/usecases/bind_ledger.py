"""Use case: register a ledger, so that this server stores its archive.

This is the only way a ledger becomes registered. A client cannot do it by
uploading. Otherwise anyone with commit access to a repository could start
a new ledger and have it stored as that repository's archive.

Every registration is written to the journal as ``archive.bound``,
including a change of what a ledger is registered for, with what it
replaced and which other ledgers the same scope has.
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

# A journal entry names the workflow that recorded it. A registration
# comes from an operator's command and not from a workflow, so its
# entries use this fixed name in that place.
WORKFLOW_ID = "archive/bound"


class BindLedgerUseCase:
    """Takes a ledger id, a repository and a scope. Returns whether anything
    changed, what the ledger was registered for before, and the scope's
    other ledgers.
    """

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
            # Write the journal entry before saving the binding. If it
            # were the other way round and the journal write failed, the
            # binding would exist with no record of it, and a retry
            # would see nothing to change and record nothing.
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
