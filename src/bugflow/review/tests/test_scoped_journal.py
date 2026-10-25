"""Partial historical mapping cannot downgrade a canonical review to legacy."""

from dataclasses import replace
from uuid import uuid4

import pytest

from bugflow.review.domain.services.scoped_journal import for_run
from bugflow.review.tests.journal import QueryableJournal
from bugflow.review.tests.payloads import whole
from bugflow.review.tests.test_publish_findings import REF, RUN, FixedClock
from bugflow.shared.domain.models.recorder import Recorder
from bugflow.shared.domain.values.repository_association import (
    AssociationConflictError,
    RepositoryAssociation,
    RepositoryAssociationUnresolvedError,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin
from bugflow.shared.infrastructure.in_memory_repository_associations import (
    InMemoryRepositoryAssociations,
)


@pytest.mark.parametrize("other", [None, "two.example/orchard/pear-tree"])
def test_partial_or_conflicting_current_run_cannot_use_legacy_history(
    other: str | None,
) -> None:
    associations = InMemoryRepositoryAssociations()
    journal = QueryableJournal(associations=associations)
    first = Recorder(REF, RUN, "v1", FixedClock().now()).entry(
        "pr.observed", "head", {}
    )
    second = replace(
        first,
        event_id=uuid4(),
        event_type="judge.invoked",
        payload=whole("judge.invoked"),
    )
    journal.append([first, second])
    mappings = [
        RepositoryAssociation(
            kind="journal",
            record_id=str(first.event_id),
            origin=RepositoryOrigin("one.example/orchard/pear-tree"),
        )
    ]
    if other is not None:
        mappings.append(
            RepositoryAssociation(
                kind="journal",
                record_id=str(second.event_id),
                origin=RepositoryOrigin(other),
            )
        )
    associations.associate(tuple(mappings))
    expected = (
        RepositoryAssociationUnresolvedError
        if other is None
        else AssociationConflictError
    )
    with pytest.raises(expected):
        for_run(journal, REF, RUN)
