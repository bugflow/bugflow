"""Tests of checking a delivery's signature."""

from bugflow.forge.infrastructure.signatures import (
    digest,
    forgejo_signature_valid,
    github_signature_valid,
)

SECRET = "a-secret"
BODY = b'{"action": "opened"}'
SIGNED = digest(SECRET.encode(), BODY)


def test_github_s_signature_has_a_prefix() -> None:
    assert github_signature_valid(SECRET, BODY, f"sha256={SIGNED}")
    assert not github_signature_valid(SECRET, BODY, SIGNED)
    assert not github_signature_valid(SECRET, BODY, None)


def test_forgejo_s_signature_has_none() -> None:
    assert forgejo_signature_valid(SECRET, BODY, SIGNED)
    assert not forgejo_signature_valid(SECRET, BODY, f"sha256={SIGNED}")
    assert not forgejo_signature_valid(SECRET, BODY, None)
    assert not forgejo_signature_valid(SECRET, BODY, "")


def test_a_signature_made_with_another_secret_or_body_is_refused() -> None:
    other_secret = digest(b"another-secret", BODY)
    other_body = digest(SECRET.encode(), b"{}")

    for wrong in (other_secret, other_body):
        assert not github_signature_valid(SECRET, BODY, f"sha256={wrong}")
        assert not forgejo_signature_valid(SECRET, BODY, wrong)
