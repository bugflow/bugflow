import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bugflow.apps.api.api import PolicyDeploying, create_api
from bugflow.apps.api.evaluation_access import ContributionEvaluationAccess
from bugflow.apps.api.evaluations import EvaluationReading
from bugflow.apps.api.role_policy_deployment_access import (
    RolePolicyDeploymentAccess,
)
from bugflow.apps.api.tests.doubles import (
    DEPLOYER,
    NOW,
    Server,
    Tokens,
    bearer,
)
from bugflow.apps.command.repository_origins import apply_mapping, inventory
from bugflow.apps.shared.submission_source import ForgeBoundedSubmissionSource
from bugflow.forge.domain.models.pull_request import (
    Authorship,
    CommitSnapshot,
    PullRequestSnapshot,
)
from bugflow.forge.infrastructure.in_memory_snapshots import (
    InMemorySnapshotStore,
)
from bugflow.forge.infrastructure.sqlalchemy_snapshots import (
    SqlAlchemySnapshotStore,
)
from bugflow.review.domain.models.history import (
    HistoryLimits,
    StoredReviewEvent,
)
from bugflow.review.infrastructure.in_memory_history import InMemoryHistory
from bugflow.review.infrastructure.in_memory_judge_archive import (
    InMemoryJudgeArchive,
)
from bugflow.review.infrastructure.sqlalchemy_journal_queries import (
    SqlAlchemyJournalQueries,
)
from bugflow.review.usecases.read_review_record import (
    ReadReviewHistoryUseCase,
    ReadReviewRecordUseCase,
)
from bugflow.shared.domain.models.recorder import Recorder
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.domain.values.repository_association import (
    RepositoryAssociation,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin
from bugflow.shared.infrastructure.in_memory_repository_associations import (
    InMemoryRepositoryAssociations,
)
from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal
from bugflow.shared.infrastructure.sqlalchemy_repository_associations import (
    SqlAlchemyRepositoryAssociations,
)

REF = PullRequestRef(forge="forgejo", owner="team", repo="project", number=7)
ONE = "one.example/team/project"
TWO = "two.example/team/project"
PREFIX = "/api/repositories/forgejo/team/project"


class Reading:
    def __init__(self, database_url: str | None) -> None:
        self.associations = (
            SqlAlchemyRepositoryAssociations(database_url)
            if database_url
            else InMemoryRepositoryAssociations()
        )
        self.snapshots = (
            SqlAlchemySnapshotStore(database_url)
            if database_url
            else InMemorySnapshotStore(self.associations)
        )
        self.history = (
            SqlAlchemyJournalQueries(database_url)
            if database_url
            else InMemoryHistory(associations=self.associations)
        )
        self.writer = SqlAlchemyJournal(database_url) if database_url else None
        self.access = ContributionEvaluationAccess(
            "issuer",
            "admin",
            {("issuer", "person"): frozenset({"person@example.com"})},
            self.snapshots,
        )

    def client(self, limits: HistoryLimits | None = None) -> TestClient:
        return TestClient(
            create_api(
                Tokens(subject="person"),
                PolicyDeploying(
                    RolePolicyDeploymentAccess(DEPLOYER), Server().deploying
                ),
                reading=EvaluationReading(
                    self.access,
                    ReadReviewHistoryUseCase(self.history, limits),
                    ReadReviewRecordUseCase(
                        self.history,
                        InMemoryJudgeArchive(),
                        ForgeBoundedSubmissionSource(self.snapshots),
                        limits,
                    ),
                ),
            )
        )

    def record(
        self,
        marker: str,
        origin: str,
        *,
        ref: PullRequestRef = REF,
        email: str = "person@example.com",
        map_event: bool = True,
        map_snapshot: bool = True,
        cited_snapshot: str | None = None,
    ) -> tuple[str, Correlation]:
        snapshot = self.snapshots.put(
            PullRequestSnapshot(
                ref=ref,
                title=marker,
                body=marker,
                head_branch="topic",
                base_branch="main",
                commits=(
                    CommitSnapshot(
                        sha=marker,
                        message=marker,
                        author=Authorship(email=email),
                    ),
                ),
                files=(),
            )
        )
        run = Correlation(workflow_id="review-" + marker, run_id="run")
        event = StoredReviewEvent(
            entry=Recorder(ref, run, "build", NOW).entry(
                "pr.observed",
                marker,
                {"snapshot_id": cited_snapshot or snapshot.snapshot_id},
            )
        )
        if self.writer is not None:
            self.writer.append((event.entry,))
        else:
            assert isinstance(self.history, InMemoryHistory)
            self.history.events[event.entry.event_id] = event
        associations = []
        if map_event:
            associations.append(
                RepositoryAssociation(
                    kind="journal",
                    record_id=str(event.entry.event_id),
                    origin=RepositoryOrigin(origin),
                )
            )
        if map_snapshot:
            associations.append(
                RepositoryAssociation(
                    kind="snapshot",
                    record_id=snapshot.snapshot_id,
                    origin=RepositoryOrigin(origin),
                )
            )
        self.associations.associate(tuple(associations))
        return snapshot.snapshot_id, run


@pytest.fixture(params=["memory", "postgres"])
def reading(request: pytest.FixtureRequest) -> Iterator[Reading]:
    result = Reading(
        request.getfixturevalue("database_url")
        if request.param == "postgres"
        else None
    )
    yield result
    if isinstance(result.associations, SqlAlchemyRepositoryAssociations):
        result.associations.close()


def test_history_separates_hosts_and_preserves_legacy_selection(
    reading: Reading,
) -> None:
    reading.record("first-host", ONE)
    reading.record("second-host", TWO)
    with reading.client() as client:
        for origin, marker in ((ONE, "first-host"), (TWO, "second-host")):
            response = client.get(
                PREFIX + "/evaluations",
                params={"pr_number": 7, "origin": origin},
                headers=bearer("nobody"),
            )
            assert response.status_code == 200
            assert response.json()["event_count"] == 1
            assert (
                response.json()["runs"][0]["correlation"]["workflow_id"]
                == "review-" + marker
            )
        legacy = client.get(
            PREFIX + "/evaluations",
            params={"pr_number": 7},
            headers=bearer("nobody"),
        )
        assert legacy.status_code == 200
        assert legacy.json()["event_count"] == 2


def test_contribution_to_one_host_grants_nothing_on_another(
    reading: Reading,
) -> None:
    reading.record("own", ONE)
    reading.record("other", TWO, email="someone-else@example.com")
    with reading.client() as client:
        response = client.get(
            PREFIX + "/evaluations",
            params={"pr_number": 7, "origin": TWO},
            headers=bearer("nobody"),
        )
        assert response.status_code == 403
        assert "other" not in response.text


def test_detail_joins_associated_history_and_snapshot(
    reading: Reading,
) -> None:
    snapshot, run = reading.record("retained", ONE)
    with reading.client() as client:
        params = {
            "workflow_id": run.workflow_id,
            "run_id": run.run_id,
            "origin": ONE,
        }
        response = client.get(
            PREFIX + "/pull-requests/7/evaluation",
            params=params,
            headers=bearer("admin"),
        )
        assert response.status_code == 200
        assert response.json()["submissions"][snapshot]["title"] == "retained"
        response = client.get(
            PREFIX + "/pull-requests/7/evaluation",
            params=params | {"origin": TWO},
            headers=bearer("admin"),
        )
        assert response.status_code == 404


@pytest.mark.parametrize(
    "map_event,map_snapshot", [(False, True), (True, False)]
)
def test_unresolved_detail_is_distinct_from_absent_content(
    reading: Reading,
    map_event: bool,
    map_snapshot: bool,
) -> None:
    _, run = reading.record(
        "unresolved", ONE, map_event=map_event, map_snapshot=map_snapshot
    )
    with reading.client() as client:
        response = client.get(
            PREFIX + "/pull-requests/7/evaluation",
            params={
                "workflow_id": run.workflow_id,
                "run_id": run.run_id,
                "origin": ONE,
            },
            headers=bearer("admin"),
        )
        assert response.status_code == 409
        assert "submissions" not in response.json()


def test_unknown_hostless_events_refuse_partial_history(
    reading: Reading,
) -> None:
    reading.record("mapped", ONE)
    reading.record("unknown", ONE, map_event=False)
    with reading.client() as client:
        response = client.get(
            PREFIX + "/evaluations",
            params={"pr_number": 7, "origin": ONE},
            headers=bearer("admin"),
        )
        assert response.status_code == 409


def test_unresolved_events_outside_the_run_do_not_block_detail(
    reading: Reading,
) -> None:
    _, run = reading.record("mapped", ONE)
    reading.record("unknown-run", ONE, map_event=False)
    with reading.client() as client:
        response = client.get(
            PREFIX + "/pull-requests/7/evaluation",
            params={
                "workflow_id": run.workflow_id,
                "run_id": run.run_id,
                "origin": ONE,
            },
            headers=bearer("admin"),
        )
        assert response.status_code == 200


@pytest.mark.parametrize("foreign", [TWO, ONE])
def test_a_snapshot_reference_cannot_cross_host_or_pr(
    reading: Reading, foreign: str
) -> None:
    other_ref = replace(REF, number=8) if foreign == ONE else REF
    snapshot, _ = reading.record("private-other", foreign, ref=other_ref)
    _, run = reading.record("selected", ONE, cited_snapshot=snapshot)
    with reading.client() as client:
        response = client.get(
            PREFIX + "/pull-requests/7/evaluation",
            params={
                "workflow_id": run.workflow_id,
                "run_id": run.run_id,
                "origin": ONE,
            },
            headers=bearer("admin"),
        )
        assert response.status_code == 200
        assert response.json()["missing_submissions"] == [snapshot]
        assert "private-other" not in response.text


def test_an_explicit_mapping_can_select_a_historical_path(
    reading: Reading,
) -> None:
    snapshot, run = reading.record(
        "historical-name", ONE, ref=replace(REF, repo="old-name")
    )
    with reading.client() as client:
        response = client.get(
            PREFIX + "/pull-requests/7/evaluation",
            params={
                "workflow_id": run.workflow_id,
                "run_id": run.run_id,
                "origin": ONE,
            },
            headers=bearer("nobody"),
        )
        assert response.status_code == 200
        assert (
            response.json()["submissions"][snapshot]["title"]
            == "historical-name"
        )


def test_canonical_history_keeps_the_event_bound(reading: Reading) -> None:
    reading.record("one", ONE)
    reading.record("two", ONE)
    with reading.client(HistoryLimits(max_events=1)) as client:
        response = client.get(
            PREFIX + "/evaluations",
            params={"pr_number": 7, "origin": ONE},
            headers=bearer("admin"),
        )
        assert response.status_code == 413


def test_origin_must_match_the_path_before_access(reading: Reading) -> None:
    with reading.client() as client:
        for origin in (
            "one.example/team/other",
            "team/project",
            "https://user:secret@one.example/team/project",
        ):
            response = client.get(
                PREFIX + "/evaluations",
                params={"pr_number": 7, "origin": origin},
                headers=bearer("admin"),
            )
            assert response.status_code == 422
            assert "secret" not in response.text


def test_mapping_makes_existing_history_readable_without_rewriting_it(
    database_url: str,
    tmp_path: Path,
) -> None:
    reading = Reading(database_url)
    snapshot, run = reading.record(
        "before-migration", ONE, map_event=False, map_snapshot=False
    )
    params = {
        "workflow_id": run.workflow_id,
        "run_id": run.run_id,
        "origin": ONE,
    }
    try:
        with reading.client() as client:
            before = client.get(
                PREFIX + "/pull-requests/7/evaluation",
                params=params,
                headers=bearer("admin"),
            )
            assert before.status_code == 409
            mapping = tmp_path / "mapping.json"
            mapping.write_text(
                json.dumps(
                    [
                        {
                            "kind": row["kind"],
                            "record_id": row["record_id"],
                            "origin": ONE,
                        }
                        for row in inventory(database_url)
                    ]
                )
            )
            assert apply_mapping(database_url, mapping) == 2
            after = client.get(
                PREFIX + "/pull-requests/7/evaluation",
                params=params,
                headers=bearer("admin"),
            )
            assert after.status_code == 200
            assert (
                after.json()["submissions"][snapshot]["title"]
                == "before-migration"
            )
            assert all(
                row["status"] == "associated"
                for row in inventory(database_url)
            )
    finally:
        assert isinstance(
            reading.associations, SqlAlchemyRepositoryAssociations
        )
        reading.associations.close()


def test_ssh_origin_is_normalized_in_the_response(reading: Reading) -> None:
    reading.record("canonical", ONE)
    with reading.client() as client:
        response = client.get(
            PREFIX + "/evaluations",
            params={
                "pr_number": 7,
                "origin": "git@ONE.EXAMPLE:team/project.git",
            },
            headers=bearer("admin"),
        )
        assert response.status_code == 200
        assert response.json()["scope"]["origin"] == ONE


def test_a_new_origin_does_not_inherit_an_old_name(reading: Reading) -> None:
    reading.record("old-name", ONE)
    with reading.client() as client:
        response = client.get(
            "/api/repositories/forgejo/team/new-name/evaluations",
            params={
                "pr_number": 7,
                "origin": "one.example/team/new-name",
            },
            headers=bearer("nobody"),
        )
        assert response.status_code == 403
