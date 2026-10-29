"""The journal, composed: where the facts go and which build is writing.

The build is a property of the process, not of any fact it records, so
it is read once, by the program, and handed to the journal's adapter to
stamp on every row. Every program that records a fact builds its
journal here rather than constructing the adapter itself, so no program
can be the one that forgets the build. A static test holds the code to
it.

A build is a full git sha or nothing. A branch name, a build number or
``latest`` in the column would read as authoritative and identify no
source tree, so a malformed value raises at startup instead of being
recorded.
"""

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from bugflow.archive.infrastructure.sqlalchemy_archive_facts import (
    UNPACKERS as ARCHIVE_UNPACKERS,
)
from bugflow.forge.domain.models.judgement import RecordedJudgement
from bugflow.forge.infrastructure.sqlalchemy_forge_facts import (
    UNPACKERS as FORGE_UNPACKERS,
)
from bugflow.forge.infrastructure.sqlalchemy_journal_queries import (
    SqlAlchemyJournalQueries,
)
from bugflow.forge.infrastructure.sqlalchemy_known_repositories import (
    UNPACKERS as DISCOVERY_UNPACKERS,
)
from bugflow.method.infrastructure.deployment_watch import DeployedFrom
from bugflow.method.infrastructure.sqlalchemy_method_facts import (
    UNPACKERS as METHOD_UNPACKERS,
)
from bugflow.review.domain.facts import JUDGE_INVOKED, STOCKTAKE_DISPATCHED
from bugflow.review.domain.models.journal_facts import JudgeInvocation
from bugflow.review.domain.models.observation import Observation
from bugflow.review.domain.models.review_entry import ReviewEntry
from bugflow.review.infrastructure.sqlalchemy_declaration_facts import (
    UNPACKERS as DECLARATION_UNPACKERS,
)
from bugflow.review.infrastructure.sqlalchemy_gnome_settings import (
    UNPACKERS as SETTING_UNPACKERS,
)
from bugflow.review.infrastructure.sqlalchemy_journal_queries import (
    SqlAlchemyJournalQueries as ReviewJournalQueries,
)
from bugflow.review.infrastructure.sqlalchemy_review_facts import (
    UNPACKERS as REVIEW_UNPACKERS,
)
from bugflow.review.infrastructure.sqlalchemy_stocktake_facts import (
    UNPACKERS as STOCKTAKE_UNPACKERS,
)
from bugflow.review.infrastructure.sqlalchemy_stocktake_facts import (
    stocktake_dispatch,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.dismissal import Dismissal
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.sqlalchemy_journal import (
    SqlAlchemyJournal,
    Unpacker,
)
from bugflow.work.domain.facts import AGENT_DISPATCHED
from bugflow.work.infrastructure.sqlalchemy_journal_queries import (
    AGENT_DISPATCH,
)
from bugflow.work.infrastructure.sqlalchemy_journal_queries import (
    SqlAlchemyJournalQueries as WorkJournalQueries,
)
from bugflow.work.infrastructure.sqlalchemy_work_facts import (
    UNPACKERS as WORK_UNPACKERS,
)

#: What writes each unpacked type's row beside its envelope (ADR 007):
#: every context's unpackers, gathered here for every program.
UNPACKERS: dict[str, Unpacker] = {
    **ARCHIVE_UNPACKERS,
    **DECLARATION_UNPACKERS,
    **FORGE_UNPACKERS,
    **DISCOVERY_UNPACKERS,
    **METHOD_UNPACKERS,
    **REVIEW_UNPACKERS,
    **SETTING_UNPACKERS,
    **STOCKTAKE_UNPACKERS,
    **WORK_UNPACKERS,
}

#: What a deployment sets to the git sha of the tree its image was built
#: from. Unset locally and in tests, where there is no build to name.
BUILD_VARIABLE = "BUILD_SHA"

_SHA = re.compile(r"[0-9a-f]{40}\Z")


#: The kinds of dispatch a runner's completion answers, each with the
#: table it is read from: a pull request reviewer's and a stocktake's.
DISPATCH_TABLES = {
    AGENT_DISPATCHED: AGENT_DISPATCH,
    STOCKTAKE_DISPATCHED: stocktake_dispatch.name,
}


def dispatch_queries(database_url: str) -> WorkJournalQueries:
    """The work context's questions of the journal, which match a
    runner's completion to either kind of dispatch."""
    return WorkJournalQueries(database_url, DISPATCH_TABLES)


def build_sha(environ: Mapping[str, str]) -> str | None:
    """Return the build this process is, or None where nothing said.

    Raises ``ValueError`` if the value is not a full git sha.
    """
    value = environ.get(BUILD_VARIABLE, "").strip()
    if not value:
        return None
    if not _SHA.match(value):
        raise ValueError(f"{BUILD_VARIABLE} is not a full git sha: {value!r}")
    return value


def stamped_journal(
    database_url: str,
    build: str | None,
    deployed_from: DeployedFrom | None = None,
    placements: Mapping[str, str] | None = None,
    unpackers: Mapping[str, Unpacker] | None = None,
) -> SqlAlchemyJournal:
    """Return the Postgres journal, stamping ``build`` on every row it
    writes. ``build`` is what ``build_sha`` read.

    ``placements`` names the journal each of the deployment's own event
    types is written to (ADR 006); the package's own are placed by its
    map, and a deployment with no facts of its own leaves it out.
    ``unpackers`` writes the typed row of each such type beside the
    package's own (ADR 007).

    ``deployed_from`` is the policy deployment the caller's reviewers
    were built from. Given, every row also names that deployment's
    repository, commit and content hash. A caller that does not review,
    or that started with no deployment in force, leaves it out and the
    three columns are empty.
    """
    return SqlAlchemyJournal(
        database_url,
        build=build,
        policy_repository=deployed_from.repository if deployed_from else None,
        policy_commit=deployed_from.commit if deployed_from else None,
        policy_content=deployed_from.content_hash if deployed_from else None,
        placements=placements,
        unpackers={**UNPACKERS, **(unpackers or {})},
    )


class DeliveryJournal:
    """The journal as the receive-delivery use case takes it: the stamped
    journal for recording, and the forge's queries for the question of
    what was received since a time. One object, because the use case
    takes one."""

    def __init__(
        self, recording: SqlAlchemyJournal, queries: SqlAlchemyJournalQueries
    ) -> None:
        self._recording = recording
        self._queries = queries

    def append(self, entries: Sequence[JournalEntry]) -> None:
        self._recording.append(entries)

    def has_event(self, event_id: UUID) -> bool:
        return self._recording.has_event(event_id)

    def received_since(
        self,
        ref: PullRequestRef,
        since: datetime,
        *,
        origin: str | None = None,
    ) -> bool:
        return self._queries.received_since(ref, since, origin=origin)


def delivery_journal(database_url: str, build: str | None) -> DeliveryJournal:
    """Return the journal the receive-delivery use case takes, over
    Postgres, stamping ``build`` on every row it writes."""
    return DeliveryJournal(
        stamped_journal(database_url, build),
        SqlAlchemyJournalQueries(database_url),
    )


class ReviewJournal:
    """The journal as the review use cases take it: the stamped journal
    for recording, and the review context's queries for what they read
    back. One object, because a use case takes one."""

    def __init__(
        self, recording: SqlAlchemyJournal, queries: ReviewJournalQueries
    ) -> None:
        self._recording = recording
        self._queries = queries

    def append(self, entries: Sequence[JournalEntry]) -> None:
        self._recording.append(entries)

    def has_event(self, event_id: UUID) -> bool:
        return self._recording.has_event(event_id)

    def entries_for_run(self, correlation: Correlation) -> list[ReviewEntry]:
        return self._queries.entries_for_run(correlation)

    def latest_acted_run(
        self, ref: PullRequestRef, excluding: Correlation
    ) -> Correlation | None:
        return self._queries.latest_acted_run(ref, excluding)

    def events_for_pull_request(
        self, ref: PullRequestRef, event_type: str
    ) -> list[ReviewEntry]:
        return self._queries.events_for_pull_request(ref, event_type)

    def events_for_repository(
        self, forge: str, repo: str, event_type: str
    ) -> list[ReviewEntry]:
        return self._queries.events_for_repository(forge, repo, event_type)

    def judgements_for_pull_request(
        self, ref: PullRequestRef
    ) -> list[RecordedJudgement]:
        """The forge's question, answered from the review's facts: the
        observation asks it of the journal the worker hands it."""
        return [
            RecordedJudgement(
                policy_id=e.fact.policy_id,
                input_hash=e.fact.identity.input_hash
                if e.fact.identity
                else None,
                status=e.fact.status,
                corpus_version=e.corpus_version,
            )
            for e in self._queries.events_for_pull_request(ref, JUDGE_INVOKED)
            if isinstance(e.fact, JudgeInvocation)
        ]

    def observations_for_pull_request(
        self, ref: PullRequestRef, origin: str | None = None
    ) -> list[Observation]:
        return self._queries.observations_for_pull_request(ref, origin)

    def dismissals_for_pull_request(
        self, ref: PullRequestRef, origin: str | None = None
    ) -> list[Dismissal]:
        return self._queries.dismissals_for_pull_request(ref, origin)


def review_journal(
    database_url: str,
    build: str | None,
    deployed_from: DeployedFrom | None = None,
) -> ReviewJournal:
    """Return the journal the review use cases take, over Postgres,
    stamping ``build`` and the deployment in ``deployed_from`` on every
    row it writes."""
    return ReviewJournal(
        stamped_journal(database_url, build, deployed_from),
        ReviewJournalQueries(database_url),
    )
