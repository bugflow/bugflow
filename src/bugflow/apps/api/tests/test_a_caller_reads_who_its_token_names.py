"""Tests of ``GET /api/me``: who a token names, as this server reads it.

The pages' account panel shows it, so a person can see which roles the
server finds in their token, and so why a page refuses them.
"""

from bugflow.apps.api.tests.doubles import ADMINISTRATOR, Server, bearer


def test_a_token_reads_its_own_subject_client_and_roles() -> None:
    answered = Server().client.get("/api/me", headers=bearer(ADMINISTRATOR))

    assert answered.status_code == 200
    assert answered.json() == {
        "subject": "machine-user-1",
        "client": "policies-pipeline",
        "roles": [ADMINISTRATOR],
    }


def test_a_token_with_no_roles_reads_none() -> None:
    answered = Server().client.get("/api/me", headers=bearer("nobody"))

    assert answered.status_code == 200
    assert answered.json()["roles"] == []


def test_no_token_reads_nothing() -> None:
    assert Server().client.get("/api/me").status_code == 401
