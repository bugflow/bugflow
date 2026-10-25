"""The review context's questions of the journal, answered from the
journal's Postgres table.

This class only reads. Writing to the journal is done by
``bugflow.shared.infrastructure.sqlalchemy_journal.SqlAlchemyJournal``.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from bugflow.review.domain.errors import HistoryTooLargeError
from bugflow.review.domain.facts import (
    ACTION_TAKEN,
    FINDING_DISMISSED,
    PR_OBSERVED,
)
from bugflow.review.domain.models.history import (
    HistoryLimits,
    HistoryScope,
    StoredReviewEvent,
)
from bugflow.review.domain.models.observation import Observation
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.dismissal import Dismissal
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.domain.values.repository_association import (
    RepositoryAssociationUnresolvedError,
)
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.serde import from_columns
from bugflow.shared.infrastructure.sqlalchemy_journal import (
    ENTRY_COLUMNS,
    VIEW_COLUMNS,
    journal,
)
from bugflow.shared.infrastructure.sqlalchemy_repository_associations import (
    association_exists,
    repository_associations,
)

#: The forge's tables this context reads an observation and a dismissal
#: from (ADR 007), named with the columns it reads. The forge context
#: defines the tables; a fact's row is keyed by its event's id.
pull_request_observation = sa.table(
    "pull_request_observation",
    sa.column("event_id", PG_UUID(as_uuid=True)),
    sa.column("snapshot_id", sa.Text),
)
finding_dismissal = sa.table(
    "finding_dismissal",
    sa.column("event_id", PG_UUID(as_uuid=True)),
    sa.column("policy_id", sa.Text),
    sa.column("reason", sa.Text),
    sa.column("actor", sa.Text),
)


def _about(
    ref: PullRequestRef, event_type: str, origin: str | None
) -> list[sa.ColumnElement[bool]]:
    """The predicates for the facts of one type about a pull request,
    and with ``origin`` for those the journal associates with it."""
    predicates: list[sa.ColumnElement[bool]] = [
        journal.c.forge == ref.forge,
        journal.c.repo == f"{ref.owner}/{ref.repo}",
        journal.c.pr_number == ref.number,
        journal.c.event_type == event_type,
    ]
    if origin is not None:
        predicates.append(
            association_exists(
                "journal", sa.cast(journal.c.event_id, sa.Text), origin
            )
        )
    return predicates


class SqlAlchemyJournalQueries:
    """The queries declared in ``review/domain/services/journal.py``."""

    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def entries_for_run(self, correlation: Correlation) -> list[JournalEntry]:
        return self._entries(
            sa.select(*ENTRY_COLUMNS)
            .where(
                journal.c.workflow_id == correlation.workflow_id,
                journal.c.run_id == correlation.run_id,
            )
            .order_by(journal.c.occurred_at, journal.c.event_type)
        )

    def entries_for_history(
        self, scope: HistoryScope, limits: HistoryLimits
    ) -> tuple[StoredReviewEvent, ...]:
        """Read bounded evidence from one database snapshot.

        The preflight transfers sizes only. The byte guard includes all
        column values and an allowance for each row's structure. The
        caller also bounds its encoded response, which can repeat facts.
        """
        predicates = [
            journal.c.forge == scope.forge,
            journal.c.pr_number.in_(scope.pr_numbers),
        ]
        if scope.correlation is not None:
            predicates.extend(
                [
                    journal.c.workflow_id == scope.correlation.workflow_id,
                    journal.c.run_id == scope.correlation.run_id,
                ]
            )
        unresolved = sa.select(
            sa.exists().where(
                *predicates,
                journal.c.repo == scope.repo,
                ~association_exists(
                    "journal", sa.cast(journal.c.event_id, sa.Text)
                ),
            )
        )
        if scope.origin is None:
            predicates.append(journal.c.repo == scope.repo)
        else:
            predicates.append(
                association_exists(
                    "journal",
                    sa.cast(journal.c.event_id, sa.Text),
                    scope.origin,
                )
            )
        size: sa.ColumnElement[int] = sa.literal(1024)
        for column in journal.c:
            size = size + sa.func.coalesce(
                sa.func.octet_length(sa.cast(column, sa.Text)), 0
            )
        candidates = (
            sa.select(size.label("bytes"))
            .where(*predicates)
            .limit(limits.max_events + 1)
            .subquery()
        )
        preflight = sa.select(
            sa.func.count(),
            sa.func.coalesce(sa.func.sum(candidates.c.bytes), 0),
        ).select_from(candidates)
        observed = pull_request_observation
        query = (
            sa.select(*VIEW_COLUMNS, observed.c.snapshot_id)
            .select_from(
                journal.outerjoin(
                    observed, observed.c.event_id == journal.c.event_id
                )
            )
            .where(*predicates)
            .order_by(
                journal.c.occurred_at,
                journal.c.recorded_at,
                journal.c.event_id,
            )
        )
        with (
            self._engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection,
            connection.begin(),
        ):
            if (
                scope.origin is not None
                and connection.execute(unresolved).scalar_one()
            ):
                raise RepositoryAssociationUnresolvedError(
                    "history contains unresolved repository associations"
                )
            count, byte_count = connection.execute(preflight).one()
            if count > limits.max_events:
                raise HistoryTooLargeError("history exceeds the event limit")
            if byte_count > limits.max_bytes:
                raise HistoryTooLargeError("history exceeds the byte limit")
            rows = connection.execute(query).mappings().all()
        return tuple(
            StoredReviewEvent(
                entry=from_columns(JournalEntry, row),
                recorded_at=row["recorded_at"],
                policy_repository=row["policy_repository"],
                policy_commit=row["policy_commit"],
                policy_content=row["policy_content"],
                snapshot_id=row["snapshot_id"],
            )
            for row in rows
        )

    def latest_acted_run(
        self, ref: PullRequestRef, excluding: Correlation
    ) -> Correlation | None:
        query = (
            sa.select(journal.c.workflow_id, journal.c.run_id)
            .where(
                journal.c.forge == ref.forge,
                journal.c.repo == f"{ref.owner}/{ref.repo}",
                journal.c.pr_number == ref.number,
                journal.c.event_type == ACTION_TAKEN,
                sa.not_(
                    sa.and_(
                        journal.c.workflow_id == excluding.workflow_id,
                        journal.c.run_id == excluding.run_id,
                    )
                ),
            )
            .order_by(
                journal.c.occurred_at.desc(), journal.c.recorded_at.desc()
            )
            .limit(1)
        )
        with self._engine.connect() as connection:
            row = connection.execute(query).first()
        if row is None:
            return None
        return Correlation(workflow_id=row.workflow_id, run_id=row.run_id)

    def events_for_pull_request(
        self, ref: PullRequestRef, event_type: str
    ) -> list[JournalEntry]:
        return self._entries(
            sa.select(*ENTRY_COLUMNS)
            .where(
                journal.c.forge == ref.forge,
                journal.c.repo == f"{ref.owner}/{ref.repo}",
                journal.c.pr_number == ref.number,
                journal.c.event_type == event_type,
            )
            .order_by(journal.c.occurred_at, journal.c.recorded_at)
        )

    def events_for_repository(
        self, forge: str, repo: str, event_type: str
    ) -> list[JournalEntry]:
        return self._entries(
            sa.select(*ENTRY_COLUMNS)
            .where(
                journal.c.forge == forge,
                journal.c.repo == repo,
                journal.c.event_type == event_type,
            )
            .order_by(journal.c.occurred_at, journal.c.recorded_at)
        )

    def observations_for_pull_request(
        self, ref: PullRequestRef, origin: str | None = None
    ) -> list[Observation]:
        observed = pull_request_observation
        query = (
            sa.select(
                journal.c.workflow_id,
                journal.c.run_id,
                journal.c.commit_sha,
                journal.c.corpus_version,
                observed.c.snapshot_id,
            )
            .select_from(
                journal.join(
                    observed, observed.c.event_id == journal.c.event_id
                )
            )
            .where(*_about(ref, PR_OBSERVED, origin))
            .order_by(journal.c.occurred_at, journal.c.recorded_at)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).all()
        return [
            Observation(
                correlation=Correlation(
                    workflow_id=row.workflow_id, run_id=row.run_id
                ),
                commit_sha=row.commit_sha,
                corpus_version=row.corpus_version,
                snapshot_id=row.snapshot_id,
            )
            for row in rows
        ]

    def dismissals_for_pull_request(
        self, ref: PullRequestRef, origin: str | None = None
    ) -> list[Dismissal]:
        dismissed = finding_dismissal
        query = (
            sa.select(
                dismissed.c.policy_id, dismissed.c.reason, dismissed.c.actor
            )
            .select_from(
                journal.join(
                    dismissed, dismissed.c.event_id == journal.c.event_id
                )
            )
            .where(*_about(ref, FINDING_DISMISSED, origin))
            .order_by(journal.c.occurred_at, journal.c.recorded_at)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).all()
        return [
            Dismissal(
                policy_id=row.policy_id, reason=row.reason, actor=row.actor
            )
            for row in rows
        ]

    def _entries(
        self, query: sa.Select[tuple[object, ...]]
    ) -> list[JournalEntry]:
        associations = repository_associations
        query = query.add_columns(associations.c.origin).select_from(
            journal.outerjoin(
                associations,
                sa.and_(
                    associations.c.kind == "journal",
                    associations.c.record_id
                    == sa.cast(journal.c.event_id, sa.Text),
                ),
            )
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return [from_columns(JournalEntry, row) for row in rows]
