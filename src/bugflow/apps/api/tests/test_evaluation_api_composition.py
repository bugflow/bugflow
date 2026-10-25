"""The configured API reads stored evidence through verified identities."""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from bugflow.apps.api.api import api_from_environment
from bugflow.apps.api.tests.test_the_api_as_it_is_run import (
    KEY,
    environment,
    token,
)
from bugflow.forge.domain.models.pull_request import (
    Authorship,
    CommitSnapshot,
    PullRequestSnapshot,
)
from bugflow.forge.infrastructure.sqlalchemy_forge_facts import (
    UNPACKERS as FORGE_UNPACKERS,
)
from bugflow.forge.infrastructure.sqlalchemy_snapshots import (
    SqlAlchemySnapshotStore,
)
from bugflow.forge.tests.payloads import observed
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.review.infrastructure.sqlalchemy_judge_archive import (
    SqlAlchemyJudgeArchive,
)
from bugflow.review.infrastructure.sqlalchemy_review_facts import (
    UNPACKERS as REVIEW_UNPACKERS,
)
from bugflow.review.tests.payloads import whole
from bugflow.shared.domain.models.recorder import Recorder
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal

PREFIX = "/api/repositories/github/owner/repo"
ALIAS = "old-address@commits.example"
NOW = datetime(2026, 10, 18, tzinfo=UTC)


def configured(
    database_url: str, *, issuer: str = "https://issuer.example"
) -> dict[str, str]:
    return environment(database_url) | {
        "EVALUATION_ADMIN_ROLE": "evaluation-admin",
        "EVALUATION_IDENTITIES": json.dumps(
            [
                {"issuer": issuer, "subject": "412345", "emails": [ALIAS]},
            ]
        ),
    }


def client(environ: dict[str, str]) -> TestClient:
    return TestClient(
        api_from_environment(environ, key=lambda _: KEY.public_key())
    )


def contributor_headers() -> dict[str, str]:
    signed = token(email="login@identity.example", **{"the-roles": []})
    return {"Authorization": f"Bearer {signed}"}


@pytest.fixture
def seeded(database_url: str) -> str:
    snapshots = SqlAlchemySnapshotStore(database_url)
    archive = SqlAlchemyJudgeArchive(database_url)
    journal = SqlAlchemyJournal(
        database_url,
        build="b" * 40,
        unpackers={**FORGE_UNPACKERS, **REVIEW_UNPACKERS},
    )
    for number, email in [(7, ALIAS), (8, "somebody-else@commits.example")]:
        ref = PullRequestRef(owner="owner", repo="repo", number=number)
        snapshot = snapshots.put(
            PullRequestSnapshot(
                ref=ref,
                title=f"PR {number}",
                body=f"Retained description {number}",
                head_branch="change",
                base_branch="main",
                commits=(
                    CommitSnapshot(
                        sha=str(number) * 40,
                        message="Change words",
                        author=Authorship(email=email),
                    ),
                ),
                files=(),
            )
        )
        exchange = archive.put(
            JudgeExchange(
                request={"policy": "ED-02", "number": number},
                response={"findings": []},
            )
        )
        recorder = Recorder(
            ref,
            Correlation(workflow_id=f"pr/{number}", run_id="run"),
            "corpus",
            NOW,
        )
        journal.append(
            [
                recorder.entry(
                    "pr.observed", "snapshot", observed(snapshot.snapshot_id)
                ),
                recorder.entry(
                    "judge.invoked",
                    "judge",
                    whole(
                        "judge.invoked",
                        policy_id="ED-02",
                        status="judged by model",
                        identity={
                            "input_hash": snapshot.snapshot_id,
                            "exchange_id": exchange,
                        },
                    ),
                ),
            ]
        )
    return database_url


def test_a_configured_alias_reads_history_and_the_retained_detail(
    seeded: str,
) -> None:
    with client(configured(seeded)) as api:
        history = api.get(
            f"{PREFIX}/evaluations",
            params={"pr_number": 7, "policy_id": "ED-02"},
            headers=contributor_headers(),
        )
        assert history.status_code == 200, history.text
        assert history.json()["observed_pr_numbers"] == [7]
        assert history.json()["event_count"] == 2
        detail = api.get(
            f"{PREFIX}/pull-requests/7/evaluation",
            params={"workflow_id": "pr/7", "run_id": "run"},
            headers=contributor_headers(),
        )
        assert detail.status_code == 200, detail.text
        evidence = detail.json()
        assert (
            next(iter(evidence["submissions"].values()))["body"]
            == "Retained description 7"
        )
        assert (
            evidence["record"]["policies"][0]["exchange"]["request"]["number"]
            == 7
        )
        assert {
            reference["availability"]
            for reference in evidence["content_references"]
        } == {"available"}


def test_another_pull_request_is_denied_and_a_mixed_list_returns_no_evidence(
    seeded: str,
) -> None:
    with client(configured(seeded)) as api:
        detail = api.get(
            f"{PREFIX}/pull-requests/8/evaluation",
            params={"workflow_id": "pr/8", "run_id": "run"},
            headers=contributor_headers(),
        )
        assert detail.status_code == 403
        history = api.get(
            f"{PREFIX}/evaluations",
            params=[("pr_number", "7"), ("pr_number", "8")],
            headers=contributor_headers(),
        )
        assert history.status_code == 403
        assert "runs" not in history.json()
        assert "Retained description" not in detail.text


def test_an_administrator_reads_a_noncontributed_pull_request(
    seeded: str,
) -> None:
    signed = token(sub="administrator", **{"the-roles": ["evaluation-admin"]})
    headers = {"Authorization": f"Bearer {signed}"}
    with client(configured(seeded) | {"EVALUATION_IDENTITIES": "[]"}) as api:
        history = api.get(
            f"{PREFIX}/evaluations", params={"pr_number": 8}, headers=headers
        )
        assert history.status_code == 200, history.text
        detail = api.get(
            f"{PREFIX}/pull-requests/8/evaluation",
            params={"workflow_id": "pr/8", "run_id": "run"},
            headers=headers,
        )
        assert detail.status_code == 200, detail.text


def test_reloading_without_an_alias_denies_the_contributor_and_deployer(
    seeded: str,
) -> None:
    with client(configured(seeded)) as before:
        assert (
            before.get(
                f"{PREFIX}/evaluations",
                params={"pr_number": 7},
                headers=contributor_headers(),
            ).status_code
            == 200
        )
    with client(configured(seeded) | {"EVALUATION_IDENTITIES": "[]"}) as after:
        assert (
            after.get(
                f"{PREFIX}/evaluations",
                params={"pr_number": 7},
                headers=contributor_headers(),
            ).status_code
            == 403
        )
        assert (
            after.get(
                f"{PREFIX}/evaluations",
                params={"pr_number": 7},
                headers={"Authorization": f"Bearer {token()}"},
            ).status_code
            == 403
        )


def test_the_verified_issuer_and_subject_bind_the_alias(seeded: str) -> None:
    with client(configured(seeded)) as api:
        for claims, status in [
            ({"sub": "other-person", "email": ALIAS}, 403),
            ({"iss": "https://other.example", "email": ALIAS}, 401),
        ]:
            response = api.get(
                f"{PREFIX}/evaluations",
                params={"pr_number": 7},
                headers={"Authorization": f"Bearer {token(**claims)}"},
            )
            assert response.status_code == status, response.text
    with client(configured(seeded, issuer="https://other.example")) as api:
        response = api.get(
            f"{PREFIX}/evaluations",
            params={"pr_number": 7},
            headers=contributor_headers(),
        )
        assert response.status_code == 403


def test_malformed_aliases_stop_startup_without_database_access() -> None:
    with pytest.raises(ValueError):
        api_from_environment(
            configured("postgresql://nowhere/none")
            | {"EVALUATION_IDENTITIES": '{"not": "a list"}'},
            key=lambda _: KEY.public_key(),
        )
