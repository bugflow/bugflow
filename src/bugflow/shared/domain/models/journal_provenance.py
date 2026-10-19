"""Resolve provenance within one repository and workflow run."""

from collections.abc import Iterable

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.repository_association import (
    AssociationConflictError,
    RepositoryAssociationUnresolvedError,
)

JournalScope = tuple[str, str, str, str, int | None]


def scope_of(entry: JournalEntry) -> JournalScope:
    return (
        entry.workflow_id,
        entry.run_id,
        entry.forge,
        entry.repo,
        entry.pr_number,
    )


def resolve_origin(
    scope: JournalScope,
    assertions: Iterable[str | None],
    retained: Iterable[str | None],
) -> str | None:
    asserted = set(assertions)
    existing = set(retained)
    if len(asserted) > 1:
        raise AssociationConflictError(
            "workflow run asserts different origins"
        )
    if asserted:
        if asserted == {None}:
            if existing - {None}:
                raise AssociationConflictError(
                    "known run origin cannot become unresolved"
                )
            return None
        if None in existing:
            raise RepositoryAssociationUnresolvedError(
                "workflow run contains unresolved journal entries"
            )
        origin = next(iter(asserted))
        if existing - {origin}:
            raise AssociationConflictError(
                "workflow run already has another origin"
            )
        return origin
    if len(existing) == 1 and None not in existing and scope[0] and scope[1]:
        inherited = next(iter(existing))
        assert inherited is not None
        # Historical mappings may name a different path. They do not
        # establish provenance for new writes at the old path.
        if inherited.split("/", 1)[1] == scope[3]:
            return inherited
    return None


def check_retry(
    entry: JournalEntry, held: JournalScope, origin: str | None
) -> None:
    if entry.origin is None and not entry.origin_asserted:
        return
    if scope_of(entry) != held:
        raise AssociationConflictError(
            "event identifier belongs to another scope"
        )
    if entry.origin is None:
        if origin is not None:
            raise AssociationConflictError(
                "known event origin cannot become unresolved"
            )
        return
    if origin is None:
        raise RepositoryAssociationUnresolvedError(
            "existing journal entry has no repository association"
        )
    if origin != entry.origin:
        raise AssociationConflictError(
            "existing journal entry has another origin"
        )


def validate_assertion(entry: JournalEntry) -> None:
    if (
        entry.origin is not None
        and entry.origin.split("/", 1)[1] != entry.repo
    ):
        raise ValueError("journal origin does not match its repository")
    if (entry.origin is not None or entry.origin_asserted) and (
        not entry.workflow_id or not entry.run_id
    ):
        raise ValueError("journal origin requires a workflow run")
