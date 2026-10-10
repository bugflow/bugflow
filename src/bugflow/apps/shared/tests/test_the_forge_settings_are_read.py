"""The forge settings every program reads the same way."""

from bugflow.apps.shared.forges import forge_token, forgejo_settings


def test_the_forge_token_is_read_before_the_github_one() -> None:
    assert forge_token({"FORGE_TOKEN": "f", "GITHUB_TOKEN": "g"}) == "f"
    assert forge_token({"GITHUB_TOKEN": "g"}) == "g"


def test_no_token_is_none() -> None:
    assert forge_token({}) is None
    assert forge_token({"FORGE_TOKEN": ""}) is None


def test_a_forgejo_needs_both_its_url_and_its_token() -> None:
    assert forgejo_settings(
        {"FORGEJO_URL": "http://forgejo.example", "FORGEJO_TOKEN": "t"}
    ) == ("http://forgejo.example", "t")
    assert forgejo_settings({"FORGEJO_URL": "http://forgejo.example"}) is None
    assert forgejo_settings({"FORGEJO_TOKEN": "t"}) is None
