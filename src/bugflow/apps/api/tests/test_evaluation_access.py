"""Recorded contributions grant access only through configured identities."""

import json

import pytest

from bugflow.apps.api.evaluation_access import access_from_configuration
from bugflow.shared.domain.values.caller import Caller
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

ISSUER = "https://identity.example"
REF = PullRequestRef(owner="owner", repo="repo", number=7)
CALLER = Caller(subject="person", client="client", roles=frozenset())


class Contributions:
    def __init__(self) -> None:
        self.records = {REF: frozenset({"Person@example.com"})}
        self.reads: list[tuple[PullRequestRef, frozenset[str]]] = []

    def has_contribution(
        self, ref: PullRequestRef, emails: frozenset[str]
    ) -> bool:
        self.reads.append((ref, emails))
        return bool(self.records.get(ref, frozenset()) & emails)


def identity(
    *,
    issuer: str = ISSUER,
    subject: str = "person",
    email: str = "Person@example.com",
) -> dict[str, object]:
    return {"issuer": issuer, "subject": subject, "emails": [email]}


def test_a_configured_contributors_access_is_independent_of_client() -> None:
    contributions = Contributions()
    access = access_from_configuration(
        ISSUER, None, json.dumps([identity()]), contributions
    )
    assert access.may_read(CALLER, REF)
    assert access.may_read(
        Caller("person", "another-client", frozenset()), REF
    )
    assert (
        contributions.reads == [(REF, frozenset({"Person@example.com"}))] * 2
    )
    assert not access.may_read(
        CALLER, PullRequestRef(owner="owner", repo="repo", number=8)
    )


def test_administrators_need_no_alias_or_contribution_lookup() -> None:
    contributions = Contributions()
    access = access_from_configuration(
        ISSUER, "review-admin", "[]", contributions
    )
    assert access.may_read(
        Caller("admin", "client", frozenset({"review-admin"})), REF
    )
    assert contributions.reads == []


def test_a_policy_deployer_has_no_implicit_read_access() -> None:
    contributions = Contributions()
    access = access_from_configuration(
        ISSUER, "review-admin", "[]", contributions
    )
    assert not access.may_read(
        Caller("person", "client", frozenset({"policy-deployer"})), REF
    )
    assert contributions.reads == []


@pytest.mark.parametrize(
    "configured",
    [identity(issuer="https://other.example"), identity(subject="other")],
)
def test_an_alias_for_another_identity_grants_nothing(
    configured: dict[str, object],
) -> None:
    contributions = Contributions()
    access = access_from_configuration(
        ISSUER, None, json.dumps([configured]), contributions
    )
    assert not access.may_read(CALLER, REF)
    assert contributions.reads == []


def test_removing_an_alias_takes_effect_when_configuration_is_rebuilt() -> (
    None
):
    contributions = Contributions()
    before = access_from_configuration(
        ISSUER, None, json.dumps([identity()]), contributions
    )
    after = access_from_configuration(ISSUER, None, "[]", contributions)
    assert before.may_read(CALLER, REF)
    assert not after.may_read(CALLER, REF)


def test_email_case_is_preserved_and_an_empty_admin_role_is_disabled() -> None:
    contributions = Contributions()
    access = access_from_configuration(
        ISSUER,
        "",
        json.dumps([identity(email="person@example.com")]),
        contributions,
    )
    assert not access.may_read(CALLER, REF)
    assert contributions.reads == [(REF, frozenset({"person@example.com"}))]
    assert not access.may_read(
        Caller("unknown", "client", frozenset({""})), REF
    )


@pytest.mark.parametrize(
    "configured",
    [
        {},
        None,
        "identities",
        [None],
        [{}],
        [identity() | {"other": "value"}],
        [identity(subject="")],
        [identity(subject=" person")],
        [identity(email=" ")],
        [identity(email="Person@example.com ")],
        [identity(email="*@example.com")],
        [identity() | {"emails": "Person@example.com"}],
        [identity() | {"emails": []}],
        [identity() | {"emails": [123]}],
        [identity() | {"emails": ["a@example.com", "a@example.com"]}],
        [identity(), identity()],
        [identity(), identity(subject="other")],
    ],
)
def test_invalid_or_ambiguous_configuration_is_refused(
    configured: object,
) -> None:
    with pytest.raises(ValueError):
        access_from_configuration(
            ISSUER, None, json.dumps(configured), Contributions()
        )


@pytest.mark.parametrize(
    "encoded",
    [
        "not json",
        '[{"issuer":"one","issuer":"two","subject":"person","emails":["a@b"]}]',
    ],
)
def test_malformed_json_or_duplicate_keys_are_refused(encoded: str) -> None:
    with pytest.raises(ValueError):
        access_from_configuration(ISSUER, None, encoded, Contributions())


def test_distinct_issuers_may_assign_the_same_email() -> None:
    access = access_from_configuration(
        ISSUER,
        None,
        json.dumps(
            [
                identity(),
                identity(
                    issuer="https://other.example", subject="another-person"
                ),
            ]
        ),
        Contributions(),
    )
    assert access.may_read(CALLER, REF)
