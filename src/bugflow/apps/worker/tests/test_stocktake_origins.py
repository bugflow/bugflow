"""Repository-wide reviews select and retain one configured source."""

from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest

from bugflow.apps.shared.journals import review_journal
from bugflow.review.domain.models.grading import Grading
from bugflow.review.dtos.review_range import CollectRangeReviewRequest
from bugflow.review.dtos.take_stock import TakeStockRequest
from bugflow.review.tests.journal import QueryableJournal
from bugflow.review.tests.test_a_stocktake_reviews_its_range import (
    AT,
    RUN,
    Clock,
    FakeAgent,
    dispatch,
    grade,
    grading_call,
)
from bugflow.review.usecases.review_range import CollectRangeReviewUseCase
from bugflow.review.usecases.take_stock import TakeStockUseCase
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.repository_association import (
    AssociationConflictError,
    RepositoryAssociation,
    RepositoryAssociationUnresolvedError,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin
from bugflow.shared.infrastructure.sqlalchemy_repository_associations import (
    SqlAlchemyRepositoryAssociations,
)

REPO = "orchard/pear-tree"
ORIGIN = f"github.com/{REPO}"
OTHER = f"other.test/{REPO}"


@pytest.fixture(params=["memory", "postgres"])
def store(request: pytest.FixtureRequest) -> Any:
    if request.param == "memory":
        journal = QueryableJournal()
        return journal, journal._associations
    url = request.getfixturevalue("database_url")
    return review_journal(url, None), SqlAlchemyRepositoryAssociations(url)


def fact(
    kind: str,
    origin: str | None,
    days: int,
    pr: int | None = None,
    head: str = "head",
) -> JournalEntry:
    return JournalEntry(
        event_id=uuid4(),
        occurred_at=AT - timedelta(days=days),
        event_type=kind,
        forge="github",
        repo=REPO,
        pr_number=pr,
        commit_sha=head,
        corpus_version=None,
        workflow_id="previous",
        run_id=str(uuid4()),
        # A merge's payload is its delivery; a mark's is the range it
        # covered, here one that merged nothing, and the commit it
        # stopped at.
        payload=(
            {"delivery_id": f"delivery-{head}"}
            if kind == "pr.merged"
            else {
                "layer": "weekly",
                "since": None,
                "until": (AT - timedelta(days=days)).isoformat(),
                "merged": 0,
                "pull_requests": [],
                "base_sha": None,
                "head_sha": head,
            }
        ),
        origin=origin,
    )


def request(origin: str | None = ORIGIN) -> TakeStockRequest:
    return TakeStockRequest(
        forge="github",
        repo=REPO,
        layer="weekly",
        correlation=RUN,
        origin=origin,
    )


def test_only_same_origin_merges_and_marks_define_the_range(
    store: Any,
) -> None:
    journal, _ = store
    journal.append(
        [
            fact("stocktake.taken", ORIGIN, 7, head="base"),
            fact("stocktake.taken", OTHER, 0, head="foreign-base"),
            fact("stocktake.taken", None, 0, head="unresolved-base"),
            fact("pr.merged", ORIGIN, 1, 1, "same-head"),
            fact("pr.merged", OTHER, 1, 2, "foreign-head"),
            fact("pr.merged", None, 1, 3, "unresolved-head"),
        ]
    )
    result = TakeStockUseCase(journal, Clock()).execute(request())
    assert (result.merged, result.base_sha, result.head_sha) == (
        1,
        "base",
        "same-head",
    )
    assert result.since == AT - timedelta(days=7)
    entries = journal.entries_for_run(RUN)
    assert len(entries) == 1 and entries[0].origin == ORIGIN
    assert entries[0].payload["pull_requests"] == [1]
    assert entries[0].pr_number is None


def test_every_range_step_and_model_call_retains_the_stocktake_origin(
    store: Any,
) -> None:
    journal, _ = store
    TakeStockUseCase(journal, Clock()).execute(request())
    agent = FakeAgent(
        findings=[{"where": "file", "quote": "text", "claim": "problem"}]
    )
    response: Any = dispatch(agent, journal)
    assert agent.tasks[0].origin == ORIGIN
    collected = CollectRangeReviewUseCase(agent, journal, Clock()).execute(
        CollectRangeReviewRequest(
            forge="github",
            repo=REPO,
            layer="weekly",
            agent_id="safety",
            head_sha="a" * 40,
            handle=response.handle,
            correlation=RUN,
        )
    )
    assert collected.run is not None
    grade(
        Grading(status="warn", detail="problem", calls=(grading_call(),)),
        journal,
    )
    entries = journal.entries_for_run(RUN)
    assert {e.event_type for e in entries} >= {
        "stocktake.taken",
        "stocktake.dispatched",
        "stocktake.reviewed",
        "stocktake.found",
        "stocktake.graded",
        "llm.called",
    }
    assert all(e.origin == ORIGIN and e.pr_number is None for e in entries)


@pytest.mark.parametrize(
    "held, new, error",
    [
        (None, ORIGIN, RepositoryAssociationUnresolvedError),
        (ORIGIN, OTHER, AssociationConflictError),
        (ORIGIN, None, AssociationConflictError),
    ],
)
def test_a_retry_cannot_assign_or_change_origin(
    store: Any, held: str | None, new: str | None, error: type[Exception]
) -> None:
    journal, _ = store
    take = TakeStockUseCase(journal, Clock())
    take.execute(request(held))
    before = journal.entries_for_run(RUN)
    with pytest.raises(error):
        take.execute(request(new))
    assert journal.entries_for_run(RUN) == before


@pytest.mark.parametrize("other", [None, OTHER])
def test_partially_mapped_runs_refuse_dispatch_before_contacting_runner(
    store: Any, other: str | None
) -> None:
    journal, associations = store
    first = replace(
        fact("stocktake.taken", None, 0),
        workflow_id=RUN.workflow_id,
        run_id=RUN.run_id,
    )
    second = replace(first, event_id=uuid4())
    journal.append([first, second])
    mappings = [
        RepositoryAssociation(
            "journal", str(first.event_id), RepositoryOrigin(ORIGIN)
        )
    ]
    if other is not None:
        mappings.append(
            RepositoryAssociation(
                "journal", str(second.event_id), RepositoryOrigin(other)
            )
        )
    associations.associate(tuple(mappings))
    agent = FakeAgent()
    with pytest.raises(
        (AssociationConflictError, RepositoryAssociationUnresolvedError)
    ):
        dispatch(agent, journal)
    assert not agent.tasks
    assert len(journal.entries_for_run(RUN)) == 2


def test_legacy_stocktakes_keep_hostless_selection_without_provenance(
    store: Any,
) -> None:
    journal, _ = store
    journal.append(
        [fact("pr.merged", OTHER, 1, 1), fact("pr.merged", None, 1, 2)]
    )
    result = TakeStockUseCase(journal, Clock()).execute(request(None))
    assert result.merged == 2
    agent = FakeAgent()
    dispatch(agent, journal)
    assert agent.tasks[0].origin is None
    assert all(e.origin is None for e in journal.entries_for_run(RUN))
