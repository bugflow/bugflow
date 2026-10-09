"""Use case: check and store one event a client sends. This is the protocol's
"append" operation.

The keeper does the checking and storing. This use case does two other
things. It decides whether the caller may append, and it writes the outcome
to the journal: ``archive.sealed`` when the event was stored,
``archive.refused`` with the kind of refusal when it was not.

A caller who may not append, or a ledger that is not registered, is refused
before the keeper is asked. Nothing is written to the journal in that case.

After a new event is stored, the search index is asked to catch up, if the
application provided a way to ask.
"""

from bugflow.archive.domain import facts
from bugflow.archive.domain.admission import admitted
from bugflow.archive.domain.errors import ArchiveRefusedError
from bugflow.archive.domain.models.binding import ArchiveBinding
from bugflow.archive.domain.models.description import Description
from bugflow.archive.domain.repositories.bindings import BindingRepository
from bugflow.archive.domain.services.archive_access import (
    ArchiveAccessService,
)
from bugflow.archive.domain.services.indexing import IndexingRequestService
from bugflow.archive.domain.services.keeping import KeepingService
from bugflow.archive.dtos.append_event import (
    AppendEventRequest,
    AppendEventResponse,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService

# A journal entry names the workflow that recorded it. An append comes
# from a client's request and not from a workflow, so its entries use
# this fixed name in that place.
WORKFLOW_ID = "archive/kept"


class AppendEventUseCase:
    """Takes an event with its files and claims from a caller. Returns what is
    stored of the ledger afterwards, and whether the event was new.
    """

    def __init__(
        self,
        bindings: BindingRepository,
        access: ArchiveAccessService,
        keeping: KeepingService,
        journal: RecordingService,
        clock: ClockService,
        run_id: str,
        indexing: IndexingRequestService | None = None,
    ) -> None:
        self._bindings = bindings
        self._access = access
        self._keeping = keeping
        self._journal = journal
        self._clock = clock
        self._run_id = run_id
        self._indexing = indexing

    def execute(self, request: AppendEventRequest) -> AppendEventResponse:
        binding = admitted(
            self._access.may_append(request.caller, request.ledger_id),
            self._bindings,
            request.ledger_id,
        )
        try:
            answer = self._keeping.append(
                request.ledger_id,
                request.name,
                request.data,
                request.files,
                request.claims,
                request.caller.subject,
                request.following,
            )
        except ArchiveRefusedError as refusal:
            self._journal.append([self._refused(binding, request, refusal)])
            raise
        # Written even when the event was already stored. The id is made
        # from the event, so the journal still ends up with one entry.
        # And if the entry could not be written the first time, the
        # client's retry writes it.
        self._journal.append(
            [self._sealed(binding, request, answer.description)]
        )
        if answer.appended and self._indexing is not None:
            # So the new files can be searched straight away. If this
            # request is lost, the scheduled catch-up covers it.
            self._indexing.request_catch_up(request.ledger_id)
        kept = answer.description
        return AppendEventResponse(
            ledger_id=kept.ledger_id,
            head=kept.head,
            events=kept.events,
            root=kept.root,
            erased=kept.erased,
            protocols=kept.protocols,
            retiring=kept.retiring,
            appended=answer.appended,
        )

    def _sealed(
        self,
        binding: ArchiveBinding,
        request: AppendEventRequest,
        kept: Description,
    ) -> JournalEntry:
        return JournalEntry(
            event_id=facts.sealed_id(request.ledger_id, request.name),
            occurred_at=self._clock.now(),
            event_type=facts.SEALED,
            forge=binding.forge,
            repo=binding.repo,
            pr_number=None,
            commit_sha=None,
            corpus_version=None,
            workflow_id=WORKFLOW_ID,
            run_id=self._run_id,
            payload={
                "ledger_id": request.ledger_id,
                "scope": binding.scope,
                "name": request.name,
                "head": kept.head,
                "root": kept.root,
                "events": kept.events,
                "files": len(request.files),
                "bytes": sum(len(data) for data in request.files.values()),
                "caller": request.caller.subject,
                "client": request.caller.client,
                "claims": dict(request.claims),
            },
        )

    def _refused(
        self,
        binding: ArchiveBinding,
        request: AppendEventRequest,
        refusal: ArchiveRefusedError,
    ) -> JournalEntry:
        when = self._clock.now()
        return JournalEntry(
            event_id=facts.refused_id(
                request.ledger_id, request.name, refusal.kind, when
            ),
            occurred_at=when,
            event_type=facts.REFUSED,
            forge=binding.forge,
            repo=binding.repo,
            pr_number=None,
            commit_sha=None,
            corpus_version=None,
            workflow_id=WORKFLOW_ID,
            run_id=self._run_id,
            payload={
                "ledger_id": request.ledger_id,
                "scope": binding.scope,
                "name": request.name,
                "kind": refusal.kind,
                "caller": request.caller.subject,
                "client": request.caller.client,
            },
        )
