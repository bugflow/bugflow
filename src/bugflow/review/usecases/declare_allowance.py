"""Use case: allow a scope to spend per one cadence, or revoke that
allowance.

This is the only way an allowance changes. Every change is written to
the journal as ``allowance.declared``, with who made it and what it
replaced, before the allowance is saved, so an allowance never stands
without its record. A declaration that changes nothing writes nothing.
"""

import json

from bugflow.review.domain.facts import ALLOWANCE_DECLARED, declaration_id
from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.domain.services.spend_bindings import (
    SpendBindingsService,
)
from bugflow.review.dtos.declare_allowance import (
    DeclareAllowanceRequest,
    DeclareAllowanceResponse,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.domain.values.budget import Budget

#: The workflow a declaration's entry names. A declaration comes from an
#: operator and not from a workflow, so its entries use this fixed name.
WORKFLOW_ID = "operator/declare"


def held(
    bindings: SpendBindingsService, scope: SpendScope, per: str
) -> Budget | None:
    """The allowance this scope holds for that cadence, matched by its
    whole key: a scope holds one allowance per cadence."""
    return next(
        (
            one.budget
            for one in bindings.bindings()
            if one.scope == scope and one.per == per
        ),
        None,
    )


def payload(
    scope: SpendScope, per: str, budget: Budget | None, was: Budget | None
) -> dict[str, object]:
    """The payload of an allowance's fact: the scope beyond its
    repository, the cadence, and what it holds after and held before.
    None is an allowance not held, and a limit held and None is none."""
    return {
        "owner": scope.owner,
        "layer": scope.layer,
        "agent_id": scope.agent_id,
        "per": per,
        "held": budget is not None,
        "usd": budget.usd if budget else None,
        "turns": budget.turns if budget else None,
        "was_held": was is not None,
        "was_usd": was.usd if was else None,
        "was_turns": was.turns if was else None,
    }


class DeclareAllowanceUseCase:
    def __init__(
        self,
        bindings: SpendBindingsService,
        journal: RecordingService,
        clock: ClockService,
        run_id: str,
    ) -> None:
        self._bindings = bindings
        self._journal = journal
        self._clock = clock
        self._run_id = run_id

    def execute(
        self, request: DeclareAllowanceRequest
    ) -> DeclareAllowanceResponse:
        scope, per = request.scope, request.per
        was = held(self._bindings, scope, per)
        if request.budget != was:
            self._journal.append([self._entry(request, was)])
            if request.budget is None:
                self._bindings.revoke(scope, per)
            else:
                self._bindings.declare(
                    SpendBinding(scope=scope, budget=request.budget, per=per)
                )
        return DeclareAllowanceResponse(
            scope=scope,
            per=per,
            held=held(self._bindings, scope, per),
            was=was,
        )

    def _entry(
        self, request: DeclareAllowanceRequest, was: Budget | None
    ) -> JournalEntry:
        when = self._clock.now()
        scope = request.scope
        said = {
            **payload(scope, request.per, request.budget, was),
            "declared_by": request.declared_by,
        }
        return JournalEntry(
            event_id=declaration_id(
                ALLOWANCE_DECLARED,
                scope.forge,
                scope.repo,
                json.dumps(said, sort_keys=True),
                when=when,
            ),
            occurred_at=when,
            event_type=ALLOWANCE_DECLARED,
            forge=scope.forge,
            repo=scope.repo,
            pr_number=None,
            commit_sha=None,
            corpus_version=None,
            workflow_id=WORKFLOW_ID,
            run_id=self._run_id,
            agent_id=scope.agent_id or None,
            payload=said,
        )
